import json
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from board.ingest import text_fingerprint
from board.models import Post

from .base import BoardTestCase

TOKEN = "test-token"


@override_settings(INGEST_TOKEN=TOKEN)
class IngestTests(BoardTestCase):
    def send(self, token=TOKEN, **fields):
        data = {"source_id": "chan:1", "kind": "announcement", "title": "Hello", "year": 3}
        data.update(fields)
        return self.client.post(
            reverse("board:ingest_post"), json.dumps(data),
            content_type="application/json", headers={"X-Ingest-Token": token},
        )

    def deadline(self, days=2):
        return (timezone.now() + timedelta(days=days)).isoformat()

    def test_wrong_token_is_rejected(self):
        self.assertEqual(self.send(token="nope").status_code, 403)
        self.assertFalse(Post.objects.exists())

    @override_settings(INGEST_TOKEN="")
    def test_switched_off_without_token(self):
        self.assertEqual(self.send(token="").status_code, 404)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse("board:ingest_post")).status_code, 405)

    def test_creates_assignment_with_course_level_and_bot_author(self):
        response = self.send(kind="assignment", course_code="dsc 301", year=0,
                             programs=["ds"], deadline=self.deadline(),
                             submission_url="https://forms.gle/abc")
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.kind, Post.Kind.ASSIGNMENT)
        self.assertEqual(post.course, self.ds_only)
        self.assertEqual(post.year, self.level3)  # taken from the course
        self.assertEqual(post.program, self.ds)
        self.assertEqual(post.submission_url, "https://forms.gle/abc")
        self.assertEqual(post.created_by.username, "whatsapp-bot")
        self.assertFalse(post.created_by.is_active)

    def test_course_matched_by_name_hint(self):
        self.send(course_hint="DS only", year=0)
        self.assertEqual(Post.objects.get().course, self.ds_only)

    def test_same_message_twice_is_imported_once(self):
        self.send()
        response = self.send()
        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(Post.objects.count(), 1)

    def test_no_programs_means_whole_level(self):
        self.send(programs=[])
        self.assertIsNone(Post.objects.get().program)

    def test_two_programs_make_two_posts(self):
        self.send(programs=["ds", "mse"])
        self.assertEqual(set(Post.objects.values_list("program__slug", flat=True)), {"ds", "mse"})

    def test_assignment_without_course_becomes_announcement(self):
        self.send(kind="assignment", deadline=self.deadline())
        post = Post.objects.get()
        self.assertEqual(post.kind, Post.Kind.ANNOUNCEMENT)
        self.assertIsNotNone(post.deadline)

    def test_bad_link_and_wrong_program_are_dropped(self):
        self.send(course_code="MSE 301", programs=["ds"], resource_url="javascript:alert(1)")
        post = Post.objects.get()
        self.assertEqual(post.resource_url, "")
        self.assertIsNone(post.program)

    def test_past_deadline_on_announcement_is_cleared(self):
        self.send(deadline=(timezone.now() - timedelta(days=3)).isoformat())
        self.assertIsNone(Post.objects.get().deadline)

    def test_unknown_level_is_shown_on_every_level(self):
        response = self.send(year=0, programs=["ds"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(Post.objects.values_list("year__number", "program__slug")),
                         {(2, "ds"), (3, "ds")})
        self.assertEqual(set(Post.objects.values_list("source_id", flat=True)),
                         {"chan:1:L2:ds", "chan:1:L3:ds"})
        self.assertTrue(self.send(year=0).json()["duplicate"])  # still imported once

    def test_bad_json(self):
        response = self.client.post(reverse("board:ingest_post"), "not json",
                                    content_type="application/json",
                                    headers={"X-Ingest-Token": TOKEN})
        self.assertEqual(response.status_code, 400)

    def test_imported_post_shows_on_board(self):
        self.send(title="FROM-WHATSAPP")
        response = self.client.get(reverse("board:list"), {"year": 3, "program": "ds"})
        self.assertContains(response, "FROM-WHATSAPP")

    def test_courses_list_needs_token_and_shows_current_semester(self):
        url = reverse("board:ingest_courses")
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.get(url, headers={"X-Ingest-Token": TOKEN})
        codes = {c["code"] for c in response.json()["courses"]}
        self.assertIn("DSC 301", codes)

    def test_same_text_with_another_id_is_imported_once(self):
        self.send(source_id="chan:1", text="Quiz on *Sunday*\nLevel 3")
        response = self.send(source_id="telegram:9:9", text="quiz on Sunday  Level 3")
        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(Post.objects.count(), 1)

    def test_different_text_is_a_new_post(self):
        self.send(source_id="chan:1", text="Quiz on Sunday")
        self.send(source_id="chan:2", text="Quiz on Monday")
        self.assertEqual(Post.objects.count(), 2)

    def test_check_only_reports_duplicates_without_creating(self):
        def check(**fields):
            return self.send(check_only=True, **fields).json()["duplicate"]

        self.assertFalse(check(source_id="chan:1", text="Hello students"))
        self.assertFalse(Post.objects.exists())
        self.send(source_id="chan:1", text="Hello students")
        self.assertTrue(check(source_id="chan:1", text="Hello students"))
        self.assertTrue(check(source_id="other:5", text="hello   students"))


    def test_several_levels_make_one_post_each(self):
        self.send(years=[2, 3], year=None)
        self.assertEqual(set(Post.objects.values_list("year__number", flat=True)), {2, 3})


class FingerprintTests(BoardTestCase):
    def test_ignores_spacing_case_and_formatting(self):
        self.assertEqual(text_fingerprint("*Quiz*  on\n_Sunday_"), text_fingerprint("quiz on sunday"))
        self.assertEqual(text_fingerprint("كويز\u200f يوم الأحد"), text_fingerprint("كويز يوم الأحد"))

    def test_empty_text_has_no_fingerprint(self):
        self.assertIsNone(text_fingerprint(""))
        self.assertIsNone(text_fingerprint("  * _ "))
        self.assertIsNone(text_fingerprint(None))
