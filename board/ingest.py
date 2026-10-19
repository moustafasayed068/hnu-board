"""WhatsApp import: one of the two write paths outside Django Admin (see also telegram.py).

The bot in `whatsapp-bot/` reads the faculty WhatsApp channel, turns each message
into fields with an LLM and POSTs them here. Both views are protected by a shared
secret (INGEST_TOKEN). With no token set, they return 404 as if they didn't exist.
"""
import hashlib
import hmac
import json
import re
import unicodedata
from copy import copy

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import AcademicYear, Course, Post, Program

MAX_FIXES = 6  # safety stop for the fix-and-retry loop in save_post


def check_token(request):
    """404 when the import is switched off, False when the token is wrong."""
    token = settings.INGEST_TOKEN
    if not token:
        raise Http404
    given = request.headers.get("X-Ingest-Token", "")
    # compare_digest takes the same time for any input, so the token can't be guessed byte by byte.
    return hmac.compare_digest(given.encode(), token.encode())


def bot_user():
    """The account bot posts are credited to. Inactive: it can never log in."""
    user, created = get_user_model().objects.get_or_create(
        username=settings.INGEST_USERNAME, defaults={"is_active": False}
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user


@require_GET
def ingest_courses(request):
    """Current-semester courses, so the bot's LLM can pick the right course code."""
    if not check_token(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    courses = [
        {"code": c.code, "name": c.name, "level": c.year.number}
        for c in Course.objects.current().select_related("year")
    ]
    return JsonResponse({"courses": courses})


@csrf_exempt  # called by the bot, not a browser form; the token replaces CSRF protection
@require_POST
def ingest_post(request):
    """Create a published post (or one per program) from one WhatsApp message."""
    if not check_token(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        data = json.loads(request.body)
        source_id = str(data["source_id"])[:180]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "bad json or missing source_id"}, status=400)

    text_hash = text_fingerprint(data.get("text"))
    if data.get("check_only"):  # the bot asks before spending an LLM call on the message
        return JsonResponse({"duplicate": is_duplicate(source_id, text_hash)})
    result = publish(data, source_id, text_hash)
    status = 422 if "error" in result else 200
    return JsonResponse(result, status=status)


def text_fingerprint(text):
    """SHA-256 of the message text with formatting, spaces and case removed, or None.

    WhatsApp and a copy forwarded to Telegram can differ in spacing and in *bold* or
    _italic_ marks, so those are ignored; any real change in wording gives a new hash.
    """
    if not text or not str(text).strip():
        return None
    text = unicodedata.normalize("NFKC", str(text))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")  # zero-width marks
    text = re.sub(r"[\s*_~`]+", "", text).casefold()
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def is_duplicate(source_id=None, text_hash=None):
    """True if this message (by id, or by its text) is already on the board."""
    query = Q(pk__in=[])
    if source_id:
        query |= Q(source_id=source_id) | Q(source_id__startswith=source_id + ":")
    if text_hash:
        query |= Q(text_hash=text_hash)
    return Post.objects.filter(query).exists()


def publish(data, source_id, text_hash=None):
    """Turn parsed fields into published posts. Shared by the WhatsApp and Telegram imports.

    Returns {"created": [ids]}, {"created": [], "duplicate": True} or {"error": ...}.
    """
    if is_duplicate(source_id, text_hash):
        return {"created": [], "duplicate": True}

    course = find_course(data.get("course_code"), data.get("course_hint"))
    numbers = level_numbers(data)
    if course and len(numbers) <= 1:
        numbers = [course.year.number]  # one level: the course decides it
    # Several levels: one post per level. None known (e.g. a notice for all students):
    # every level, rather than guessing one.
    levels = AcademicYear.objects.order_by("number")
    years = list(levels.filter(number__in=numbers)) or list(levels)
    if not years:
        return {"error": "could not tell the level"}

    programs = list(Program.objects.filter(slug__in=data.get("programs") or [], is_active=True))
    now = timezone.now()
    published_at = min(to_datetime(data.get("posted_at")) or now, now)

    created = []
    for year in years:
        for program in programs or [None]:  # no program = the whole level
            post_course = course if course and course.year == year else None
            post = build_post(data, year, program, post_course, published_at, text_hash,
                              post_source_id(source_id, year if len(years) > 1 else None, program))
            try:
                save_post(post)
            except ValidationError as error:
                return {"error": error.message_dict, "created": created}
            created.append(post.pk)
    return {"created": created}


def level_numbers(data):
    """Levels the message is for: "years": [3, 4] (LLM, tags) or the older single "year": 3."""
    values = data.get("years")
    if not isinstance(values, list):
        values = [data.get("year")]
    numbers = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in numbers:
            numbers.append(number)
    return numbers


def post_source_id(source_id, year=None, program=None):
    """<message id>[:L<level>][:<program>] so every copy of one message has its own id."""
    parts = [source_id]
    if year:
        parts.append(f"L{year.number}")
    if program:
        parts.append(program.slug)
    return ":".join(parts)


def message_source_id(source_id):
    """The message part of a post's source_id, without the :L<level> and :<program> suffixes."""
    if not source_id:
        return None
    slugs = set(Program.objects.values_list("slug", flat=True))
    parts = source_id.split(":")
    if parts and parts[-1] in slugs:
        parts.pop()
    if parts and re.fullmatch(r"L\d", parts[-1]):
        parts.pop()
    return ":".join(parts)


def unique(items):
    """Distinct items, first-seen order (None counts as an item)."""
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def rebuild_copies(posts, years=None, programs=None, course="keep", kind=None):
    """Replace the copies of one imported message with one post per (level, program).

    Anything not given stays as it is on the first copy. A course is kept only on the
    copy of its own level. Runs in a transaction: on a validation error nothing changes.
    """
    template = posts[0]
    years = years or unique(p.year for p in posts)
    programs = programs or unique(p.program for p in posts)
    course = template.course if course == "keep" else course
    kind = kind or template.kind
    base = message_source_id(template.source_id) or f"import:fix:{template.pk}"
    saved = []
    with transaction.atomic():
        Post.objects.filter(pk__in=[p.pk for p in posts]).delete()
        for year in years:
            for program in programs:
                post = copy(template)
                post.pk = post.id = None
                post._state.adding = True
                post.year, post.program, post.kind = year, program, kind
                post.course = course if course and course.year == year else None
                post.source_id = post_source_id(base, year if len(years) > 1 else None, program)
                save_post(post)
                saved.append(post)
    return saved


def build_post(data, year, program, course, published_at, text_hash, source_id):
    return Post(
        kind=data.get("kind") if data.get("kind") in Post.Kind.values else Post.Kind.ANNOUNCEMENT,
        title=(data.get("title") or "Untitled")[:200],
        body=data.get("body") or "",
        year=year,
        program=program,
        course=course,
        deadline=to_datetime(data.get("deadline")),
        submission_url=(data.get("submission_url") or "")[:200],
        resource_url=(data.get("resource_url") or "")[:200],
        published_at=published_at,
        created_by=bot_user(),
        source_id=source_id,
        text_hash=text_hash,
    )


def find_course(code, hint):
    """Match by exact code first, then by name. Only this semester's courses."""
    courses = Course.objects.current()
    if code:
        match = courses.filter(code__iexact=code.strip()).first()
        if match:
            return match
    if hint:
        hint = hint.strip()
        return (
            courses.filter(Q(code__iexact=hint) | Q(name__iexact=hint)).first()
            or courses.filter(name__icontains=hint).first()
        )
    return None


def to_datetime(value):
    """ISO 8601 text -> aware datetime, or None. Naive times are taken as Cairo time."""
    if not value:
        return None
    try:
        parsed = parse_datetime(str(value))
    except ValueError:
        return None
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def save_post(post):
    """Validate like the admin form would; repair what the LLM got wrong, then save.

    Each pass fixes the fields Django complained about, so a slightly wrong message
    still lands on the board (as an announcement if it can't be a valid assignment).
    """
    for _ in range(MAX_FIXES):
        try:
            post.full_clean()
        except ValidationError as error:
            fix(post, error.message_dict)
        else:
            post.save()
            return
    post.full_clean()  # still invalid: let the caller report the errors


def fix(post, errors):
    if "submission_url" in errors:
        post.submission_url = ""
    if "resource_url" in errors:
        post.resource_url = ""
    if "program" in errors:
        post.program = None  # reach the whole level instead
    if "year" in errors and post.course_id:
        post.year = post.course.year
    if "title" in errors:
        post.title = "Untitled"
    if "kind" in errors:
        post.kind = Post.Kind.ANNOUNCEMENT
    assignment_problem = {"course", "__all__"} & errors.keys()
    if post.is_assignment and (assignment_problem or "deadline" in errors):
        post.kind = Post.Kind.ANNOUNCEMENT  # no course or no valid deadline
    elif "deadline" in errors:
        post.deadline = None  # e.g. a deadline before the publication date
