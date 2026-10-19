"""Telegram import: forward a channel post to the board's Telegram bot and it is published.

Works without the WhatsApp bot (the PC can be off): Telegram calls this webhook on
PythonAnywhere. Only the Telegram accounts in TELEGRAM_ALLOWED_USER_IDS can post.
Posts are deduplicated by their text (ingest.text_fingerprint), so the same post
caught up later by the WhatsApp bot is not published twice.
"""
import hmac
import io
import json
import logging
import re
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .ingest import bot_user, is_duplicate, publish, rebuild_copies, text_fingerprint, unique
from .llm import parse_post
from .models import AcademicYear, Course, Post, Program, SiteNotice

logger = logging.getLogger(__name__)

HELP = (
    "Forward or paste a post from the faculty channel and I'll publish it on the board "
    "and tell you what I saved.\n\n"
    "Something wrong? Reply to my message with the fix, e.g. #L3 or #DSC301 or #mse, "
    "or #delete to remove it.\n\n"
    "Tags (also usable when forwarding, optional):\n"
    "#L4  level 4 (#L3 #L4 = both levels; no level = all levels)\n"
    "#ds #mse #rse  program (several = one post each), #all = whole level\n"
    "#DSC411  course code (no space)\n"
    "#assignment or #announcement\n\n"
    "#delete  remove the post (only when replying)\n\n"
    "/notice <text>  show a \"What's new\" banner on the site (/notice off hides it)\n"
    "/status  last imports and counts\n"
    "/backup  send me a backup of the database"
)

PROGRAM_TAGS = {"ds", "mse", "rse"}
KIND_TAGS = {"assignment", "announcement"}
TAG = re.compile(r"#([A-Za-z]+\d*)")
POST_LINK = re.compile(r"/post/(\d+)/change/")


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
        reply = handle_message(message, request)
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


def handle_message(message, request):
    """Publish the message text and return the reply for the sender."""
    user_id = (message.get("from") or {}).get("id")
    if user_id not in settings.TELEGRAM_ALLOWED_USER_IDS:
        return f"You're not allowed to post here. (Your Telegram ID is {user_id}.)"

    text = (message.get("text") or message.get("caption") or "").strip()
    if not text or text in ("/start", "/help"):
        return HELP
    if text == "/notice" or text.startswith("/notice "):
        return set_notice(text[len("/notice"):].strip())
    if text == "/status":
        return status()
    if text == "/backup":
        send_backup(message["chat"]["id"])
        return "Backup sent above. Keep it private: it contains the admins' password hashes."
    replied_to = (message.get("reply_to_message") or {}).get("text") or ""
    if POST_LINK.search(replied_to):
        return correct_posts(replied_to, text, request)

    text, overrides, unknown = read_tags(text)
    overrides.pop("delete", None)  # only means something in a reply
    if unknown:
        return f"Unknown tag(s): {', '.join(unknown)}. Nothing published.\n\n{HELP}"
    if not text:
        return HELP

    # Fingerprint without the tags, so it matches the same post coming from WhatsApp.
    text_hash = text_fingerprint(text)
    existing = Post.objects.filter(text_hash=text_hash).first() if text_hash else None
    if existing:  # checked before the LLM call, to save quota
        return f"Already on the board. Nothing added.\n{describe([existing], request)}"

    posted_at = message_time(message)
    courses = [
        {"code": c.code, "name": c.name, "level": c.year.number}
        for c in Course.objects.current().select_related("year")
    ]
    data = parse_post(text, posted_at, courses)
    data.update(overrides)  # your tags win over the AI's guess
    if "years" in overrides and "course_code" not in overrides:
        # The AI's course must be on a level you tagged, or the post would move to its level.
        levels = {c["code"].lower(): c["level"] for c in courses}
        guessed = (data.get("course_code") or "").strip().lower()
        if guessed and levels.get(guessed) not in overrides["years"]:
            data["course_code"] = data["course_hint"] = ""
    data.pop("year", None)  # only "years" from here on
    if not data.get("years") and not data.get("course_code") and settings.TELEGRAM_DEFAULT_LEVEL:
        data["years"] = [settings.TELEGRAM_DEFAULT_LEVEL]  # optional default; else every level
    data["posted_at"] = posted_at.isoformat()
    # You chose to forward it, so it's published even if the LLM thinks it's not relevant.

    source_id = f"telegram:{message['chat']['id']}:{message.get('message_id')}"
    result = publish(data, source_id, text_hash)
    if result.get("duplicate"):
        return "Already on the board. Nothing added."
    if "error" in result:
        if result["error"] == "could not tell the level":
            return "Couldn't tell the level. Add a tag like #L4 and send it again."
        return f"The site refused it: {result['error']}"
    posts = list(Post.objects.filter(pk__in=result["created"]).select_related("year", "program", "course"))
    return f"Published:\n{describe(posts, request)}"


def correct_posts(replied_to, text, request):
    """Fix (or delete) the posts listed in the bot message you replied to, using your tags.

    The copies of one message (one per level and/or program) are rebuilt from the first one,
    so e.g. #L3 on a post shown to all levels leaves a single Level 3 post.
    """
    rest, overrides, unknown = read_tags(text)
    if unknown or rest or not overrides:
        return ("To fix a post, reply with tags only, e.g. #L3, #DSC301, #mse, #all, "
                "#assignment or #delete.")
    ids = [int(pk) for pk in POST_LINK.findall(replied_to)]
    # Only the imports' own posts: TAs' posts are changed in the admin, by their authors.
    posts = list(Post.objects.filter(pk__in=ids, created_by=bot_user())
                 .select_related("year", "program", "course").order_by("pk"))
    if not posts:
        return "That post is gone (or wasn't made by the import)."
    if overrides.get("delete"):
        Post.objects.filter(pk__in=[p.pk for p in posts]).delete()
        return f"Deleted: {posts[0].title}"

    course, years, programs = "keep", None, None
    if "course_code" in overrides:
        course = Course.objects.get(code=overrides["course_code"])
        years = [course.year]
    elif "years" in overrides:
        levels = list(AcademicYear.objects.filter(number__in=overrides["years"]).order_by("number"))
        if levels:
            years = levels
    if "programs" in overrides:
        programs = list(Program.objects.filter(slug__in=overrides["programs"], is_active=True)) or [None]
    try:
        saved = rebuild_copies(posts, years=years, programs=programs, course=course,
                               kind=overrides.get("kind"))
    except ValidationError as error:
        return f"Couldn't save the fix: {error.messages}"
    return f"Updated:\n{describe(saved, request)}"


def read_tags(text):
    """Split "#L4 #ds #DSC411 ..." tags out of the text.

    Returns (text without the tags, field overrides, unknown tags). Tags that look like
    course codes but match no course this semester are reported as unknown.
    """
    overrides, unknown, programs = {}, [], []
    codes = {c.code.replace(" ", "").lower(): c.code for c in Course.objects.current()}

    def take(match):
        tag = match.group(1).lower()
        if re.fullmatch(r"l[1-4]", tag):
            overrides.setdefault("years", [])
            if int(tag[1]) not in overrides["years"]:
                overrides["years"].append(int(tag[1]))
        elif tag in PROGRAM_TAGS:
            programs.append(tag)
        elif tag == "delete":
            overrides["delete"] = True
        elif tag == "all":
            overrides["programs"] = []
        elif tag in KIND_TAGS:
            overrides["kind"] = tag
        elif tag in codes:
            overrides["course_code"] = codes[tag]
        elif re.fullmatch(r"[a-z]{2,4}\d{3}", tag):
            unknown.append(match.group(0))
        else:
            return match.group(0)  # an ordinary hashtag in the post: keep it
        return ""

    text = TAG.sub(take, text).strip()
    if programs:
        overrides["programs"] = programs
    return text, overrides, unknown


def describe(posts, request):
    """What was saved (once), where it shows, and a link per copy to fix it in the admin."""
    if not posts:
        return ""
    first = posts[0]
    parts = [first.title, first.get_kind_display()]
    if first.course:
        parts.append(first.course.code)
    if first.deadline:
        parts.append("due " + timezone.localtime(first.deadline).strftime("%a %d %b %H:%M"))
    where = ", ".join(
        f"{p.year}" + (f" {p.program.slug.upper()}" if p.program else "") for p in posts
    )
    if len(posts) == AcademicYear.objects.count() and len(unique(p.year for p in posts)) > 1:
        where += "  (level unknown, shown to all levels: reply #L1-#L4 to pick one)"
    links = "\n".join(
        request.build_absolute_uri(reverse("admin:board_post_change", args=[p.pk])) for p in posts
    )
    return " · ".join(parts) + f"\nShown on: {where}\nEdit:\n{links}"


def set_notice(text):
    """/notice <text> publishes a "What's new" banner; /notice off hides it."""
    if not text:
        current = SiteNotice.current()
        return f"Current notice: {current.text}" if current else "No notice is shown. Send /notice <text>."
    if text.lower() == "off":
        SiteNotice.objects.filter(is_active=True).update(is_active=False)
        return "Notice hidden."
    notice = SiteNotice(text=text[:300])
    notice.full_clean()
    SiteNotice.objects.filter(is_active=True).update(is_active=False)  # one banner at a time
    notice.save()
    return f"Notice is live on the site:\n{notice.text}"


def status():
    """Health check for the owner: is each import still bringing posts in?"""
    imported = Post.objects.filter(created_by=bot_user())
    from_telegram = imported.filter(source_id__startswith="telegram:")
    from_whatsapp = imported.exclude(source_id__startswith="telegram:")
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    now = timezone.now()

    def last(posts):
        post = posts.order_by("-created_at").first()
        if not post:
            return "never"
        ago = now - post.created_at
        when = f"{ago.days} days ago" if ago.days else f"{ago.seconds // 3600} h ago"
        return f"{when} ({post.title[:40]})"

    lines = [
        f"WhatsApp bot, last post: {last(from_whatsapp)}",
        f"Telegram, last post: {last(from_telegram)}",
        f"This month: {from_whatsapp.filter(created_at__gte=month_start).count()} from WhatsApp, "
        f"{from_telegram.filter(created_at__gte=month_start).count()} from Telegram",
        f"On the board: {Post.objects.published().count()} posts, "
        f"{Post.objects.published().filter(kind=Post.Kind.ASSIGNMENT, deadline__gte=now).count()} open assignments",
    ]
    newest = from_whatsapp.order_by("-created_at").first()
    if newest and now - newest.created_at > timedelta(days=3):
        lines.append("⚠️ Nothing from the WhatsApp bot for 3+ days. Is the PC bot running?")
    lines.append("Cohere usage: dashboard.cohere.com (free key: 1,000 calls/month)")
    return "\n".join(lines)


def send_backup(chat_id):
    """Send a dumpdata backup (same as PLAN.md "Backups") to the chat as a file."""
    out = io.StringIO()
    call_command("dumpdata", "board", "auth.user", "auth.group", indent=2, stdout=out)
    name = f"backup-{timezone.localdate():%Y-%m-%d}.json"
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{name}\"\r\n"
        f"Content-Type: application/json\r\n\r\n".encode(),
        out.getvalue().encode(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument"
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(request, timeout=30).close()


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
