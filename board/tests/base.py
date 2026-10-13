from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from board.models import AcademicYear, Course, Post, Program

User = get_user_model()


# The test client speaks plain HTTP, so don't redirect it to HTTPS on the server.
# Pin the semester so the tests don't depend on today's date.
@override_settings(SECURE_SSL_REDIRECT=False, CURRENT_SEMESTER="1")
class BoardTestCase(TestCase):
    """Shared data: two levels, three programs, a few courses and one TA."""

    @classmethod
    def setUpTestData(cls):
        cls.level2 = AcademicYear.objects.create(number=2, name="Level 2")
        cls.level3 = AcademicYear.objects.create(number=3, name="Level 3")
        cls.ds = Program.objects.create(name="Data Science", slug="ds")
        cls.mse = Program.objects.create(name="MSE", slug="mse")
        cls.rse = Program.objects.create(name="RSE", slug="rse")

        cls.common = Course.objects.create(code="GEN 317", name="Common", year=cls.level3)
        cls.ds_only = Course.objects.create(code="DSC 301", name="DS only", year=cls.level3)
        cls.ds_only.programs.add(cls.ds)
        cls.shared = Course.objects.create(code="DSC 302", name="Shared", year=cls.level3)
        cls.shared.programs.add(cls.ds, cls.mse)
        cls.mse_only = Course.objects.create(code="MSE 301", name="MSE only", year=cls.level3)
        cls.mse_only.programs.add(cls.mse)
        cls.retake = Course.objects.create(code="BAS 204", name="Retake", year=cls.level2)

        cls.ta = cls.make_ta("ta_a")

    @staticmethod
    def make_ta(username):
        user = User.objects.create_user(username, password="pw", is_staff=True)
        user.groups.add(Group.objects.get(name="Teaching assistants"))
        return user

    @classmethod
    def make_post(cls, title="Post", **fields):
        """Create a post directly (skips clean()). Level defaults to the course's, or 3."""
        course = fields.get("course")
        fields.setdefault("kind", Post.Kind.ANNOUNCEMENT)
        fields.setdefault("year", course.year if course else cls.level3)
        fields.setdefault("created_by", cls.ta)
        return Post.objects.create(title=title, **fields)

    @classmethod
    def make_assignment(cls, title="Assignment", minutes=60 * 24, **fields):
        """An assignment due `minutes` from now (negative = already closed)."""
        fields.setdefault("course", cls.common)
        fields.setdefault("deadline", timezone.now() + timedelta(minutes=minutes))
        return cls.make_post(title, kind=Post.Kind.ASSIGNMENT, **fields)
