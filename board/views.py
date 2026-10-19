from datetime import timedelta, timezone as dt_timezone

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_safe

from .forms import BoardFilterForm
from .models import Course, Post, current_semester

PAGE_SIZE = 20


@require_safe
def board_list(request):
    """The public board: a picker, plus the posts for a level + program (or one course)."""
    form = BoardFilterForm(request.GET)
    form.is_valid()  # invalid values are simply left out of cleaned_data
    year = form.cleaned_data.get("year")
    program = form.cleaned_data.get("program")
    course = form.cleaned_data.get("course")
    kind = form.cleaned_data.get("type")

    if year and program:
        posts = Post.objects.visible_to(year, program)
        if course:
            posts = posts.filter(course=course)
        # Only offer the courses this board can actually show.
        course_field = form.fields["course"]
        course_field.queryset = course_field.queryset.offered_to(program).filter(year=year)
    elif course:
        # Retake case: one course's posts, whatever the level or program.
        posts = Post.objects.published().filter(course=course)
    else:
        posts = None  # nothing chosen yet: show the picker only

    context = {
        "form": form,
        "show_board": posts is not None,
        "year": year,
        "program": program,
        "course": course,
        "kind": kind,
        "semester": Course.Semester(current_semester()).label,
    }
    if posts is not None:
        if kind:
            posts = posts.filter(kind=kind)
        posts = posts.select_related("course", "year", "program")

        upcoming = Q(kind=Post.Kind.ASSIGNMENT, deadline__gte=timezone.now())
        context["due_soon"] = posts.filter(upcoming).order_by("deadline")
        recent = posts.exclude(upcoming)  # newest first, from Post.Meta.ordering
        context["page"] = Paginator(recent, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "board/list.html", context)


@require_safe
def post_detail(request, pk):
    """One published post. Scheduled (future) posts return 404."""
    posts = Post.objects.published().select_related("course", "year", "program")
    post = get_object_or_404(posts, pk=pk)
    return render(request, "board/detail.html", {"post": post})


@require_safe
def post_calendar(request, pk):
    """The assignment's deadline as an .ics file, with reminders a day and 2 hours before.

    Opening it on a phone adds the event to the student's own calendar, which then does
    the reminding (the site itself sends no notifications).
    """
    post = get_object_or_404(Post.objects.published().select_related("course"), pk=pk)
    if not post.deadline:
        raise Http404
    stamp = "%Y%m%dT%H%M%SZ"
    start = post.deadline.astimezone(dt_timezone.utc)
    title = f"{post.course.code}: {post.title}" if post.course else post.title
    link = request.build_absolute_uri(post.get_absolute_url())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//HNU Board//EN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:post-{post.pk}@{request.get_host()}",
        f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(stamp)}",
        f"DTSTART:{start.strftime(stamp)}",
        f"DTEND:{(start + timedelta(minutes=30)).strftime(stamp)}",
        f"SUMMARY:{ics_text('Deadline · ' + title)}",
        f"DESCRIPTION:{ics_text(link)}",
        f"URL:{link}",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Deadline tomorrow", "TRIGGER:-P1D", "END:VALARM",
        "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Deadline in 2 hours", "TRIGGER:-PT2H", "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    response = HttpResponse("\r\n".join(fold(line) for line in lines) + "\r\n",
                            content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="deadline-{post.pk}.ics"'
    return response


def ics_text(value):
    """Escape text for an .ics field."""
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def fold(line):
    """.ics lines longer than 75 bytes continue on the next line, starting with a space."""
    data, parts = line.encode(), []
    while len(data) > 75:
        cut = 75 if not parts else 74
        while (data[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        parts.append(data[:cut].decode())
        data = data[cut:]
    parts.append(data.decode())
    return "\r\n ".join(parts)
