from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from board.models import Post

from .base import BoardTestCase

User = get_user_model()

ADD_URL = reverse("admin:board_post_add")
LIST_URL = reverse("admin:board_post_changelist")


def change_url(post):
    return reverse("admin:board_post_change", args=[post.pk])


class PostAdminTests(BoardTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_ta = cls.make_ta("ta_b")
        cls.superuser = User.objects.create_superuser("boss", password="pw")
        cls.others_post = cls.make_post("B's post", created_by=cls.other_ta)

    def form_data(self, **overrides):
        """What the admin post form submits for a valid announcement."""
        published = timezone.localtime() - timedelta(minutes=1)
        data = {
            "kind": "announcement",
            "title": "From the form",
            "body": "",
            "year": self.level3.pk,
            "program": "",
            "course": "",
            "resource_url": "",
            "submission_url": "",
            "deadline_0": "",
            "deadline_1": "",
            "published_at_0": published.strftime("%Y-%m-%d"),
            "published_at_1": published.strftime("%H:%M:%S"),
            "notes": "",
        }
        return {**data, **overrides}

    # --- login ---

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(ADD_URL)
        self.assertRedirects(response, f"{reverse('admin:login')}?next={ADD_URL}")

    def test_non_staff_is_denied(self):
        User.objects.create_user("student", password="pw")
        self.client.login(username="student", password="pw")
        response = self.client.get(ADD_URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    # --- ownership ---

    def test_created_by_is_always_the_logged_in_ta(self):
        self.client.force_login(self.ta)
        response = self.client.post(ADD_URL, self.form_data(created_by=self.other_ta.pk))
        self.assertRedirects(response, LIST_URL)
        self.assertEqual(Post.objects.get(title="From the form").created_by, self.ta)

    def test_ta_can_edit_own_post_and_stays_owner(self):
        post = self.make_post("Mine")
        self.client.force_login(self.ta)
        self.client.post(change_url(post), self.form_data(title="Mine, edited"))
        post.refresh_from_db()
        self.assertEqual(post.title, "Mine, edited")
        self.assertEqual(post.created_by, self.ta)

    def test_ta_cannot_see_or_edit_another_tas_post(self):
        self.client.force_login(self.ta)
        self.assertNotContains(self.client.get(LIST_URL), "B's post")

        # Admin answers "not found" by redirecting to its index with a warning.
        for response in (
            self.client.get(change_url(self.others_post)),
            self.client.post(change_url(self.others_post), self.form_data(title="Hacked")),
        ):
            self.assertRedirects(response, reverse("admin:index"))
        self.others_post.refresh_from_db()
        self.assertEqual(self.others_post.title, "B's post")

    def test_ta_cannot_delete_another_tas_post(self):
        self.client.force_login(self.ta)
        delete_url = reverse("admin:board_post_delete", args=[self.others_post.pk])
        self.client.post(delete_url, {"post": "yes"})
        self.client.post(
            LIST_URL,
            {"action": "delete_selected", "_selected_action": [self.others_post.pk], "post": "yes"},
        )
        self.assertTrue(Post.objects.filter(pk=self.others_post.pk).exists())

    def test_permission_checks_do_not_rely_on_the_queryset(self):
        from django.contrib import admin
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.ta
        post_admin = admin.site._registry[Post]
        self.assertFalse(post_admin.has_change_permission(request, self.others_post))
        self.assertFalse(post_admin.has_delete_permission(request, self.others_post))

    def test_superuser_can_edit_any_post(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(change_url(self.others_post)).status_code, 200)
        self.client.post(change_url(self.others_post), self.form_data(title="Fixed by admin"))
        self.others_post.refresh_from_db()
        self.assertEqual(self.others_post.title, "Fixed by admin")
        self.assertEqual(self.others_post.created_by, self.other_ta)

    # --- validation reaches the admin form ---

    def test_admin_form_runs_post_validation(self):
        self.client.force_login(self.ta)
        response = self.client.post(
            ADD_URL, self.form_data(kind="assignment", resource_url="javascript:alert(1)")
        )
        self.assertEqual(response.status_code, 200)  # form shown again with errors
        self.assertFalse(Post.objects.filter(title="From the form").exists())
        errors = response.context["adminform"].form.errors
        self.assertTrue({"course", "deadline", "resource_url"} <= set(errors))

    # --- academic structure ---

    def test_ta_can_view_but_not_change_courses(self):
        self.client.force_login(self.ta)
        url = reverse("admin:board_course_change", args=[self.common.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(
            url, {"code": "HACK", "name": "Hacked", "year": self.level3.pk}
        )
        self.assertEqual(response.status_code, 403)
        self.common.refresh_from_db()
        self.assertEqual(self.common.code, "GEN 317")

    def test_changelists_load_for_superuser(self):
        self.client.force_login(self.superuser)
        for model in ("academicyear", "program", "course", "post"):
            response = self.client.get(reverse(f"admin:board_{model}_changelist"))
            self.assertEqual(response.status_code, 200, model)
