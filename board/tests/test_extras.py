"""Link previews, clickable links, calendar files, the home-screen app and the notice banner."""
from datetime import timedelta, timezone as dt_timezone

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from board.models import SiteNotice
from board.templatetags.board_extras import linkify

from .base import BoardTestCase

BOARD = {"year": 3, "program": "ds"}


class LinkifyTests(BoardTestCase):
    def test_links_are_clickable_and_safe(self):
        html = linkify("Form: https://forms.gle/abc. Thanks")
        self.assertIn('<a href="https://forms.gle/abc" target="_blank" rel="noopener noreferrer">', html)
        self.assertIn("</a>. Thanks", html)  # the full stop isn't part of the link

    def test_html_is_escaped_and_only_http_links(self):
        html = linkify('<script>x</script> javascript:alert(1) "quoted"')
        self.assertNotIn("<script>", html)
        self.assertNotIn("<a", html)

    def test_line_breaks_and_arabic_punctuation(self):
        html = linkify("الرابط: https://x.com/a،\nسطر")
        self.assertIn('href="https://x.com/a"', html)
        self.assertIn("<br>", html)

    def test_post_page_shows_links_in_body(self):
        post = self.make_post(body="Slides: https://drive.google.com/x")
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, 'href="https://drive.google.com/x"')


class SharePreviewTests(BoardTestCase):
    def test_post_page_has_its_title_and_deadline_in_preview(self):
        post = self.make_assignment("Lab 3 report")
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, '<meta property="og:title" content="Lab 3 report">', html=False)
        self.assertContains(response, 'property="og:description" content="Deadline:')
        self.assertContains(response, "icon-512.png")

    def test_board_has_level_and_program_in_preview(self):
        response = self.client.get(reverse("board:list"), BOARD)
        self.assertContains(response, 'content="Level 3 · Data Science | HNU Board"')

    def test_pages_link_the_app_manifest(self):
        response = self.client.get(reverse("board:list"))
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'rel="apple-touch-icon"')


class RememberBoardTests(BoardTestCase):
    def test_board_page_marks_itself_for_remembering(self):
        response = self.client.get(reverse("board:list"), BOARD)
        self.assertContains(response, 'data-remember-board="?year=3&amp;program=ds"')

    def test_home_has_the_continue_slot(self):
        self.assertContains(self.client.get(reverse("board:list")), "data-resume")


class CalendarTests(BoardTestCase):
    def test_assignment_downloads_ics_with_reminders(self):
        post = self.make_assignment("Lab 3 report")
        response = self.client.get(reverse("board:post_calendar", args=[post.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertIn("BEGIN:VEVENT", body)
        self.assertIn("SUMMARY:Deadline · GEN 317: Lab 3 report", body)
        self.assertIn("TRIGGER:-P1D", body)
        self.assertIn("TRIGGER:-PT2H", body)
        utc = post.deadline.astimezone(dt_timezone.utc)
        self.assertIn(f"DTSTART:{utc:%Y%m%dT%H%M%SZ}", body)

    def test_long_arabic_title_is_folded_without_breaking_letters(self):
        post = self.make_assignment("تسليم تقرير المعمل الثالث لمادة " * 4)
        body = self.client.get(reverse("board:post_calendar", args=[post.pk])).content
        body.decode("utf-8")  # still valid UTF-8 after folding
        self.assertTrue(all(len(line) <= 75 for line in body.split(b"\r\n")))

    def test_no_deadline_or_hidden_post_is_404(self):
        announcement = self.make_post()
        future = self.make_assignment(published_at=timezone.now() + timedelta(days=1))
        for post in (announcement, future):
            url = reverse("board:post_calendar", args=[post.pk])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_post_page_has_add_to_calendar_button(self):
        post = self.make_assignment()
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, reverse("board:post_calendar", args=[post.pk]))


class NoticeTests(BoardTestCase):
    def test_newest_active_notice_shows_on_every_page(self):
        SiteNotice.objects.create(text="Old news", is_active=False)
        SiteNotice.objects.create(text="Add the board to your home screen!")
        response = self.client.get(reverse("board:list"))
        self.assertContains(response, "Add the board to your home screen!")
        self.assertNotContains(response, "Old news")
        post = self.make_post()
        self.assertContains(self.client.get(post.get_absolute_url()), "What's new")

    def test_no_notice_no_banner(self):
        self.assertNotContains(self.client.get(reverse("board:list")), "data-notice=")


class AnalyticsTests(BoardTestCase):
    def test_off_by_default(self):
        self.assertNotContains(self.client.get(reverse("board:list")), "goatcounter")

    @override_settings(GOATCOUNTER_CODE="hnuboard")
    def test_on_with_code(self):
        response = self.client.get(reverse("board:list"))
        self.assertContains(response, "https://hnuboard.goatcounter.com/count")
