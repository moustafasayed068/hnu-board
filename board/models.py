from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

# Blocks javascript:, data:, ftp: and anything else that is not a normal web link.
validate_http_url = URLValidator(schemes=["http", "https"])


def current_semester():
    """1 (fall) or 2 (spring). Set DJANGO_CURRENT_SEMESTER to override the calendar guess."""
    if settings.CURRENT_SEMESTER in ("1", "2"):
        return int(settings.CURRENT_SEMESTER)
    # ponytail: guessed from the month (Sep-Jan = 1, Feb-Aug = 2); summer term counts as 2.
    # Set the env var when the real term dates differ.
    return 1 if timezone.localdate().month in (9, 10, 11, 12, 1) else 2


class AcademicYear(models.Model):
    """A level (1-4). Students know these as "Level N"."""

    number = models.PositiveSmallIntegerField(unique=True)
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ["number"]
        verbose_name = "level"

    def __str__(self):
        return self.name


class Program(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, help_text="Used in URLs: ?program=ds")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CourseQuerySet(models.QuerySet):
    def offered_to(self, program):
        """Courses of this program, plus common courses (no programs set)."""
        return self.filter(Q(programs=program) | Q(programs__isnull=True))

    def current(self):
        """Courses taught this semester: the only ones students can pick."""
        return self.filter(semester=current_semester())


class Course(models.Model):
    class Semester(models.IntegerChoices):
        FIRST = 1, "First semester"
        SECOND = 2, "Second semester"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="courses", verbose_name="level"
    )
    semester = models.PositiveSmallIntegerField(choices=Semester.choices, default=Semester.FIRST)
    programs = models.ManyToManyField(
        Program,
        blank=True,
        related_name="courses",
        help_text="Leave empty for a common course shared by every program.",
    )

    objects = CourseQuerySet.as_manager()

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class PostQuerySet(models.QuerySet):
    def published(self):
        """Posts whose publication date has arrived."""
        return self.filter(published_at__lte=timezone.now())

    def visible_to(self, year, program):
        """Published posts a student of this level and program should see this semester."""
        # A subquery of course ids (not a join) so a shared course never duplicates a post.
        courses = Course.objects.current().offered_to(program).values("pk")
        return self.published().filter(
            Q(program=program) | Q(program__isnull=True),
            Q(course__isnull=True) | Q(course__in=courses),
            year=year,
        )


class Post(models.Model):
    """An assignment or an announcement. One table so the "All" feed is one query."""

    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", "Assignment"
        ANNOUNCEMENT = "announcement", "Announcement"

    DUE_SOON_WINDOW = timedelta(days=3)

    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="posts",
        verbose_name="level",
        blank=True,
        help_text="Taken from the course if left empty.",
    )
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="posts",
        null=True,
        blank=True,
        help_text="Leave empty to reach the whole level.",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="posts",
        null=True,
        blank=True,
        help_text="Required for assignments.",
    )
    resource_url = models.URLField(blank=True, validators=[validate_http_url])
    submission_url = models.URLField(blank=True, validators=[validate_http_url])
    deadline = models.DateTimeField(null=True, blank=True, help_text="Required for assignments.")
    published_at = models.DateTimeField(
        default=timezone.now, help_text="A future date hides the post until then."
    )
    notes = models.TextField(blank=True, help_text="Extra instructions shown under the post.")
    # Set only by the WhatsApp import (board/ingest.py) so a message is never imported twice.
    source_id = models.CharField(max_length=200, unique=True, null=True, blank=True, editable=False)
    # Set by PostAdmin.save_model, never by a form. PROTECT: deactivate TAs, don't delete them.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="posts", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["year", "-published_at"]),  # Recent posts feed
            models.Index(fields=["year", "deadline"]),  # Due-soon list
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(kind="assignment")
                | (Q(course__isnull=False) & Q(deadline__isnull=False)),
                name="assignment_needs_course_and_deadline",
            )
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("board:post_detail", args=[self.pk])

    def clean(self):
        errors = {}
        if self.course_id:
            if not self.year_id:
                self.year = self.course.year
            elif self.year_id != self.course.year_id:
                errors["year"] = "This course belongs to a different level."
            course_programs = self.course.programs.all()
            if self.program_id and course_programs and self.program not in course_programs:
                errors["program"] = "This course is not offered to that program."
        elif not self.year_id:
            errors["year"] = "Choose a level, or a course to take the level from."

        if self.kind == self.Kind.ASSIGNMENT:
            if not self.course_id:
                errors["course"] = "An assignment needs a course."
            if not self.deadline:
                errors["deadline"] = "An assignment needs a deadline."
        if self.deadline and self.published_at and self.deadline < self.published_at:
            errors["deadline"] = "The deadline cannot be before the publication date."

        if errors:
            raise ValidationError(errors)

    @property
    def is_assignment(self):
        return self.kind == self.Kind.ASSIGNMENT

    @property
    def is_overdue(self):
        return self.deadline is not None and self.deadline < timezone.now()

    @property
    def is_due_soon(self):
        if self.deadline is None:
            return False
        now = timezone.now()
        return now <= self.deadline <= now + self.DUE_SOON_WINDOW

    @property
    def was_edited(self):
        """True if the post changed after it was created (shows "Updated ...")."""
        return self.updated_at - self.created_at > timedelta(minutes=1)
