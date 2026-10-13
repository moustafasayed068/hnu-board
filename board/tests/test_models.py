from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from board.models import AcademicYear, Course, Post, Program

from .base import BoardTestCase


class PostValidationTests(BoardTestCase):
    def build(self, **fields):
        """An unsaved, valid assignment; override fields to break one rule."""
        defaults = {
            "kind": Post.Kind.ASSIGNMENT,
            "title": "Sheet 1",
            "year": self.level3,
            "course": self.common,
            "deadline": timezone.now() + timedelta(days=1),
            "created_by": self.ta,
        }
        return Post(**{**defaults, **fields})

    def assert_invalid(self, field, **fields):
        with self.assertRaises(ValidationError) as caught:
            self.build(**fields).full_clean()
        self.assertIn(field, caught.exception.message_dict)

    def test_valid_assignment_passes(self):
        self.build(resource_url="https://example.com/sheet.pdf").full_clean()

    def test_assignment_needs_deadline_and_course(self):
        self.assert_invalid("deadline", deadline=None)
        self.assert_invalid("course", course=None)

    def test_database_rejects_assignment_without_deadline(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.build(deadline=None).save()

    def test_announcement_needs_neither(self):
        self.build(kind=Post.Kind.ANNOUNCEMENT, course=None, deadline=None).full_clean()

    def test_only_http_links_allowed(self):
        self.assert_invalid("resource_url", resource_url="javascript:alert(1)")
        self.assert_invalid("submission_url", submission_url="ftp://example.com/file")

    def test_course_from_another_level_rejected(self):
        self.assert_invalid("year", course=self.retake)  # level 2 course, level 3 post

    def test_program_must_be_offered_the_course(self):
        self.assert_invalid("program", course=self.mse_only, program=self.ds)
        self.build(course=self.shared, program=self.ds).full_clean()
        self.build(course=self.common, program=self.rse).full_clean()

    def test_level_copied_from_course(self):
        post = self.build(year=None, course=self.retake)
        post.full_clean()
        self.assertEqual(post.year, self.level2)

    def test_level_required_without_course(self):
        self.assert_invalid("year", kind=Post.Kind.ANNOUNCEMENT, year=None, course=None, deadline=None)

    def test_deadline_before_publication_rejected(self):
        now = timezone.now()
        self.assert_invalid("deadline", deadline=now, published_at=now + timedelta(days=1))

    def test_overdue_boundary(self):
        self.assertTrue(self.make_assignment(minutes=-1).is_overdue)
        upcoming = self.make_assignment(minutes=1)
        self.assertFalse(upcoming.is_overdue)
        self.assertTrue(upcoming.is_due_soon)
        self.assertFalse(self.make_assignment(minutes=60 * 24 * 10).is_due_soon)


class VisibleToTests(BoardTestCase):
    def titles(self, year, program):
        return sorted(Post.objects.visible_to(year, program).values_list("title", flat=True))

    def test_program_sees_own_level_wide_and_common_posts(self):
        self.make_post("level-wide")
        self.make_post("for ds", program=self.ds)
        self.make_post("common course", course=self.common)
        self.make_post("ds course", course=self.ds_only)
        self.make_post("for mse", program=self.mse)
        self.make_post("mse course", course=self.mse_only)
        self.make_post("level 2", year=self.level2)
        self.make_post("scheduled", published_at=timezone.now() + timedelta(days=1))

        self.assertEqual(
            self.titles(self.level3, self.ds),
            ["common course", "ds course", "for ds", "level-wide"],
        )

    def test_shared_course_appears_once_per_program(self):
        self.make_post("shared", course=self.shared)
        self.assertEqual(self.titles(self.level3, self.ds), ["shared"])
        self.assertEqual(self.titles(self.level3, self.mse), ["shared"])
        self.assertEqual(self.titles(self.level3, self.rse), [])


class FixtureTests(BoardTestCase):
    def test_fixture_loads(self):
        for model in (Course, Program, AcademicYear):
            model.objects.all().delete()
        call_command("loaddata", "hnu_courses", verbosity=0)
        self.assertEqual(AcademicYear.objects.count(), 4)
        self.assertEqual(set(Program.objects.values_list("slug", flat=True)), {"ds", "mse", "rse"})
        self.assertEqual(Course.objects.count(), 105)
        # Every program has courses in both semesters of levels 3 and 4.
        for program in Program.objects.all():
            for level in (3, 4):
                for semester in (1, 2):
                    courses = program.courses.filter(year__number=level, semester=semester)
                    self.assertTrue(courses.exists(), (program.slug, level, semester))
