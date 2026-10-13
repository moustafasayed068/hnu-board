from datetime import datetime, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from board.models import Course, current_semester
from board.views import PAGE_SIZE

from .base import BoardTestCase

BOARD = {"year": 3, "program": "ds"}


class BoardListTests(BoardTestCase):
    def get(self, **query):
        return self.client.get(reverse("board:list"), query)

    def test_no_filters_shows_selector(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_board"])

    def test_bad_values_show_selector_not_error(self):
        for query in ({"year": "abc", "program": "ds"}, {"year": 3, "program": "nope"},
                      {"year": 99, "program": "ds"}, {"course": "x"}, {"year": 3}):
            response = self.get(**query)
            self.assertEqual(response.status_code, 200, query)
            self.assertFalse(response.context["show_board"], query)

    def test_bad_page_and_type_do_not_break_the_board(self):
        response = self.get(**BOARD, type="bogus", page="zzz")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_board"])

    def test_board_shows_only_posts_for_that_level_and_program(self):
        self.make_post("LEVEL-WIDE")
        self.make_post("DS-COURSE", course=self.ds_only)
        self.make_post("COMMON-COURSE", course=self.common)
        self.make_post("SHARED-COURSE", course=self.shared)
        self.make_post("MSE-COURSE", course=self.mse_only)
        self.make_post("LEVEL-TWO", year=self.level2)

        response = self.get(**BOARD)
        for title in ("LEVEL-WIDE", "DS-COURSE", "COMMON-COURSE"):
            self.assertContains(response, title)
        self.assertContains(response, "SHARED-COURSE", count=1)
        self.assertNotContains(response, "MSE-COURSE")
        self.assertNotContains(response, "LEVEL-TWO")
        # Selected level and program are named on the page.
        self.assertContains(response, "Level 3 · Data Science")

    def test_type_filter(self):
        self.make_post("AN-ANNOUNCEMENT")
        self.make_assignment("AN-ASSIGNMENT")
        self.make_assignment("CLOSED-ASSIGNMENT", minutes=-5)

        response = self.get(**BOARD, type="assignment")
        self.assertContains(response, "AN-ASSIGNMENT")
        self.assertContains(response, "CLOSED-ASSIGNMENT")
        self.assertNotContains(response, "AN-ANNOUNCEMENT")

        response = self.get(**BOARD, type="announcement")
        self.assertContains(response, "AN-ANNOUNCEMENT")
        self.assertNotContains(response, "AN-ASSIGNMENT")

    def test_course_filter_on_a_board(self):
        self.make_post("ABOUT-COMMON", course=self.common)
        self.make_post("ABOUT-DS", course=self.ds_only)
        response = self.get(**BOARD, course=self.common.pk)
        self.assertContains(response, "ABOUT-COMMON")
        self.assertNotContains(response, "ABOUT-DS")

    def test_course_alone_shows_all_its_posts(self):
        # Retake case: a level 3 student following a level 2 course.
        self.make_post("RETAKE-NEWS", course=self.retake)
        self.make_assignment("RETAKE-SHEET", course=self.retake)
        self.make_post("OTHER", course=self.common)

        response = self.get(course=self.retake.pk)
        self.assertContains(response, "RETAKE-NEWS")
        self.assertContains(response, "RETAKE-SHEET")
        self.assertNotContains(response, "OTHER")

    def test_only_current_semester_courses_can_be_chosen(self):
        spring = Course.objects.create(code="DSC 304", name="Spring only", year=self.level3, semester=2)
        self.make_post("SPRING-POST", course=spring)

        # First semester: the course is not offered and its id is ignored.
        self.assertNotContains(self.get(), "Spring only")
        self.assertNotContains(self.get(**BOARD), "Spring only")
        self.assertFalse(self.get(course=spring.pk).context["show_board"])

        with self.settings(CURRENT_SEMESTER="2"):
            self.assertContains(self.get(**BOARD), "Spring only")
            self.assertContains(self.get(course=spring.pk), "SPRING-POST")
            self.assertNotContains(self.get(**BOARD), "DS only")  # a first-semester course

    def test_semester_guessed_from_the_date_when_not_set(self):
        cases = ((datetime(2026, 10, 13), 1), (datetime(2027, 1, 20), 1), (datetime(2027, 3, 1), 2))
        with self.settings(CURRENT_SEMESTER=""):
            for moment, expected in cases:
                with mock.patch("django.utils.timezone.now", return_value=timezone.make_aware(moment)):
                    self.assertEqual(current_semester(), expected, moment)

    def test_due_soon_is_nearest_first(self):
        for title, minutes in (("in 3 days", 4320), ("in 1 hour", 60), ("in 1 day", 1440)):
            self.make_assignment(title, minutes=minutes)
        due_soon = [post.title for post in self.get(**BOARD).context["due_soon"]]
        self.assertEqual(due_soon, ["in 1 hour", "in 1 day", "in 3 days"])

    def test_deadline_boundary(self):
        closed = self.make_assignment("JUST-CLOSED", minutes=-1)
        open_ = self.make_assignment("STILL-OPEN", minutes=1)

        response = self.get(**BOARD)
        self.assertEqual(list(response.context["due_soon"]), [open_])
        self.assertEqual(list(response.context["page"]), [closed])
        self.assertContains(response, "Closed", count=1)
        self.assertContains(response, "Due in")
        self.assertContains(response, "Deadline:")

    def test_recent_feed_newest_first_and_paginated(self):
        now = timezone.now()
        for age in range(PAGE_SIZE + 5):
            self.make_post(f"post {age}", published_at=now - timedelta(hours=age))

        first = self.get(**BOARD).context["page"]
        self.assertEqual(len(first), PAGE_SIZE)
        self.assertEqual(first[0].title, "post 0")
        self.assertEqual(first[1].title, "post 1")

        response = self.get(**BOARD, page=2)
        self.assertEqual(len(response.context["page"]), 5)
        # Page links keep the filters.
        self.assertContains(response, "?year=3&amp;program=ds&amp;page=1")

    def test_scheduled_post_is_hidden(self):
        post = self.make_post("NOT-YET", published_at=timezone.now() + timedelta(days=1))
        self.assertNotContains(self.get(**BOARD), "NOT-YET")
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)

    def test_post_text_is_escaped(self):
        post = self.make_post("<script>alert(1)</script>", body="<script>alert(2)</script>")
        for response in (self.get(**BOARD), self.client.get(post.get_absolute_url())):
            self.assertNotContains(response, "<script>alert")
            self.assertContains(response, "&lt;script&gt;alert(1)")

    def test_public_pages_are_read_only_and_hide_admin(self):
        post = self.make_post()
        self.assertEqual(self.client.post(reverse("board:list")).status_code, 405)
        self.assertEqual(self.client.post(post.get_absolute_url()).status_code, 405)
        for response in (self.get(), self.get(**BOARD), self.client.get(post.get_absolute_url())):
            self.assertNotContains(response, "/manage/")


class PostDetailTests(BoardTestCase):
    def test_links_are_safe_external_links(self):
        post = self.make_assignment(
            resource_url="https://example.com/sheet", submission_url="https://example.com/submit"
        )
        response = self.client.get(post.get_absolute_url())
        for url in ("https://example.com/sheet", "https://example.com/submit"):
            self.assertContains(response, f'href="{url}" target="_blank" rel="noopener noreferrer"')

    def test_missing_submission_url(self):
        post = self.make_assignment()
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, "No submission link")
        self.assertNotContains(response, 'href=""')
        self.assertNotContains(response, "Submit here")

    def test_unknown_post_is_404(self):
        self.assertEqual(self.client.get(reverse("board:post_detail", args=[9999])).status_code, 404)
