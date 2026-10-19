"""Telegram import: forward a channel post to the board's Telegram bot and it is published.

Works without the WhatsApp bot (the PC can be off): Telegram calls this webhook on
PythonAnywhere. Only the Telegram accounts in TELEGRAM_ALLOWED_USER_IDS can post.
Posts are deduplicated by their text (ingest.text_fingerprint), so the same post
caught up later by the WhatsApp bot is not published twice.
"""
import hmac
import json
import logging
import urllib.request
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .ingest import is_duplicate, publish, text_fingerprint
from .llm import parse_post
from .models import Course

logger = logging.getLogger(__name__)

HELP = (
    "Forward or paste a post from the faculty channel and I'll publish it on the board.\n"
    "If I can't tell the level, add e.g. \"Level 4\" to the text and send it again."
)


@csrf_exempt  # called by Telegram, not a browser form; the secret replaces CSRF protection
@require_POST
def telegram_webhook(request, secret):
    """Handle one Telegram update. Always answers 200 so Telegram doesn't resend it."""
    check_secret(request, secret)
    try:
        update = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ok": True})
    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not chat_id:
        return JsonResponse({"ok": True})  # edits, button presses...: nothing to do

    try:
        reply = handle_message(message)
    except Exception:  # never let one bad message make Telegram retry forever
        logger.exception("Telegram import failed")
        reply = "Something went wrong on the site. Try again later."
    send_message(chat_id, reply)
    return JsonResponse({"ok": True})


def check_secret(request, secret):
    """404 unless the import is switched on and both secrets match (URL and header)."""
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if not (settings.TELEGRAM_BOT_TOKEN and expected):
        raise Http404
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # compare_digest takes the same time for any input, so the secret can't be guessed byte by byte.
    if not (hmac.compare_digest(secret.encode(), expected.encode())
            and hmac.compare_digest(header.encode(), expected.encode())):
        raise Http404


def handle_message(message):
    """Publish the message text and return the reply for the sender."""
    user_id = (message.get("from") or {}).get("id")
    if user_id not in settings.TELEGRAM_ALLOWED_USER_IDS:
        return f"You're not allowed to post here. (Your Telegram ID is {user_id}.)"

    text = (message.get("text") or message.get("caption") or "").strip()
    if not text or text in ("/start", "/help"):
        return HELP

    text_hash = text_fingerprint(text)
    if is_duplicate(text_hash=text_hash):  # checked before the LLM call, to save quota
        return "Already on the board. Nothing added."

    posted_at = message_time(message)
    courses = [
        {"code": c.code, "name": c.name, "level": c.year.number}
        for c in Course.objects.current().select_related("year")
    ]
    data = parse_post(text, posted_at, courses)
    if not data.get("year") and settings.TELEGRAM_DEFAULT_LEVEL:
        data["year"] = settings.TELEGRAM_DEFAULT_LEVEL  # level not in the text: use the default
    data["posted_at"] = posted_at.isoformat()
    # You chose to forward it, so it's published even if the LLM thinks it's not relevant.

    source_id = f"telegram:{message['chat']['id']}:{message.get('message_id')}"
    result = publish(data, source_id, text_hash)
    if result.get("duplicate"):
        return "Already on the board. Nothing added."
    if "error" in result:
        if result["error"] == "could not tell the level":
            return "Couldn't tell the level. Add e.g. \"Level 4\" to the text and send it again."
        return f"The site refused it: {result['error']}"
    count = len(result["created"])
    extra = f" ({count} posts, one per program)" if count > 1 else ""
    return f"Published: {data.get('title') or 'Untitled'}{extra}"


def message_time(message):
    """When the post was first sent: the original time for a Telegram forward, else now."""
    stamp = (message.get("forward_origin") or {}).get("date") or message.get("forward_date")
    if stamp:
        return datetime.fromtimestamp(stamp, tz=dt_timezone.utc)
    return timezone.now()


def send_message(chat_id, text):
    """Reply in the chat. A failed reply is only logged: the post is already saved."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except Exception as error:
        logger.warning("Telegram reply failed: %s", error)
