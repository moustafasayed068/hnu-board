"""Turn a raw channel message into the fields ingest.publish() expects.

Python twin of whatsapp-bot/parser.js, used by the Telegram import (telegram.py).
One Cohere call per message; without COHERE_API_KEY (or if the call fails) a simple
regex fallback posts it as an announcement. Uses only the standard library.
"""
import json
import logging
import re
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

COHERE_URL = "https://api.cohere.com/v2/chat"

SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["assignment", "announcement"]},
        "title": {"type": "string"},
        "body": {"type": "string"},
        "years": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}},
        "programs": {"type": "array", "items": {"type": "string", "enum": ["ds", "mse", "rse"]}},
        "course_code": {"type": "string"},
        "course_hint": {"type": "string"},
        "deadline": {"type": "string"},
        "submission_url": {"type": "string"},
        "resource_url": {"type": "string"},
    },
    "required": [
        "is_relevant", "kind", "title", "body", "years", "programs",
        "course_code", "course_hint", "deadline", "submission_url", "resource_url",
    ],
}


def parse_post(text, posted_at, courses):
    """Fields for one message. `courses` is a list of {"code", "name", "level"} dicts."""
    if settings.COHERE_API_KEY:
        try:
            return parse_with_cohere(text, posted_at, courses)
        except Exception as error:  # network, quota, bad JSON: fall back, never crash the webhook
            logger.warning("Cohere parse failed, using regex: %s", error)
    return parse_with_regex(text)


def build_prompt(text, posted_at, courses):
    course_list = "\n".join(f"{c['code']} | {c['name']} | level {c['level']}" for c in courses)
    return (
        "Generate a JSON object describing this message from the WhatsApp channel of the Faculty of "
        "Computer Science & IT, Helwan National University. It was posted on "
        f"{posted_at.isoformat()}; Cairo time is UTC+03:00. Messages mix Egyptian Arabic and English.\n\n"
        "Fields:\n"
        "- is_relevant: false for greetings, notices about one specific student, polls or chit-chat\n"
        '- kind: "assignment" if students must submit something by a deadline, else "announcement"\n'
        "- title: short title (max ~80 chars), keep the original language\n"
        "- body: the message text without greetings and sign-offs\n"
        '- years: the levels / الفرقة (1-4) the message is for, as stated (e.g. "الفرقة الرابعة" or "4th year" '
        '= [4]; "الفرقة الثالثة والرابعة" = [3, 4]), or else the level of the matching course in the list '
        "below; [] if it is for all students or the level is unclear\n"
        '- programs: any of "ds" (Data Science / داتا ساينس), "mse" (Multimedia), "rse" (Robotics); '
        "empty list if the message is for everyone\n"
        '- course_code: the code of the matching course from the list below, else ""\n'
        '- course_hint: the course name as written in the message, else ""\n'
        '- deadline: ISO 8601 with +03:00 offset, resolving dates like "Saturday 17 October" to the next '
        'matching date on/after the posting date; "" if none\n'
        '- submission_url: the link where students submit (e.g. a Google Form), else ""\n'
        '- resource_url: any other link (sheet, slides, drive), else ""\n\n'
        f"Courses this semester (code | name | level):\n{course_list}\n\n"
        f'Message:\n"""\n{text}\n"""'
    )


def parse_with_cohere(text, posted_at, courses):
    body = json.dumps({
        "model": settings.COHERE_MODEL,
        "messages": [{"role": "user", "content": build_prompt(text, posted_at, courses)}],
        "response_format": {"type": "json_object", "schema": SCHEMA},
        "temperature": 0,
    }).encode()
    request = urllib.request.Request(
        COHERE_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {settings.COHERE_API_KEY}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        data = json.load(response)
    return json.loads(data["message"]["content"][0]["text"])


def parse_with_regex(text):
    """Without Cohere: an announcement; the level must be in the text (or a default)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    links = re.findall(r"https?://\S+", text)
    year = re.search(r"(?:level|الفرقة|المستوى)\s*(\d)", text, re.IGNORECASE)
    ordinals = ["الأولى", "الثانية", "الثالثة", "الرابعة"]
    named = next((i + 1 for i, word in enumerate(ordinals)
                  if f"الفرقة {word}" in text or f"المستوى {word}" in text), 0)
    return {
        "is_relevant": len(text) > 40,
        "kind": "announcement",
        "title": (lines[0][:80] if lines else "Untitled"),
        "body": text,
        "years": [int(year.group(1))] if year else ([named] if named else []),  # [] = every level
        "programs": [],
        "course_code": "",
        "course_hint": "",
        "deadline": "",
        "submission_url": "",
        "resource_url": links[0] if links else "",
    }
