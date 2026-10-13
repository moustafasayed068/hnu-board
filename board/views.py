from django.core.paginator import Paginator
from django.db.models import Q
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
