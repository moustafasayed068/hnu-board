import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from board.ingest import text_fingerprint
from board.models import Post

from .base import BoardTestCase

SECRET = "hook-secret"
ME = 111


def parsed(**fields):
    """What the LLM would return for a simple level-3 announcement."""
    data = {"is_relevant": True, "kind": "announcement", "title": "Quiz", "body": "Quiz",
            "year": 3, "programs": [], "course_code": "", "course_hint": "",
            "deadline": "", "submission_url": "", "resource_url": ""}
    data.update(fields)
    return data


@override_settings(TELEGRAM_BOT_TOKEN="bot-token", TELEGRAM_WEBHOOK_SECRET=SECRET,
                   TELEGRAM_ALLOWED_USER_IDS={ME}, TELEGRAM_DEFAULT_LEVEL=0)
@mock.patch("board.telegram.send_message")
@mock.patch("board.telegram.parse_post", return_value=parsed())
class TelegramTests(BoardTestCase):
    def send(self, text="Quiz on Sunday, Level 3", user=ME, secret=SECRET, header=SECRET, message_id=1):
        update = {"update_id": 1, "message": {
            "message_id": message_id, "date": 1792436000, "text": text,
            "from": {"id": user}, "chat": {"id": user, "type": "private"},
        }}
        return self.client.post(
            reverse("board:telegram_webhook", args=[secret]), json.dumps(update),
            content_type="application/json",
            headers={"X-Telegram-Bot-Api-Secret-Token": header},
        )

    def reply(self, send_message):
        return send_message.call_args.args[1]

    def test_forwarded_post_is_published_and_confirmed(self, parse_post, send_message):
        response = self.send()
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.title, "Quiz")
        self.assertEqual(post.year, self.level3)
        self.assertEqual(post.created_by.username, "whatsapp-bot")
        self.assertEqual(post.text_hash, text_fingerprint("Quiz on Sunday, Level 3"))
        self.assertIn("Published", self.reply(send_message))

    def test_same_text_twice_is_published_once_without_llm(self, parse_post, send_message):
        self.send(message_id=1)
        self.send(message_id=2)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(parse_post.call_count, 1)
        self.assertIn("Already on the board", self.reply(send_message))

    def test_post_already_imported_from_whatsapp_is_skipped(self, parse_post, send_message):
        self.make_post("From WhatsApp", source_id="chan:5", text_hash=text_fingerprint("Quiz on Sunday"))
        self.send(text="quiz on  *Sunday*")
        self.assertEqual(Post.objects.count(), 1)
        parse_post.assert_not_called()

    def test_stranger_cannot_post(self, parse_post, send_message):
        self.send(user=999)
        self.assertFalse(Post.objects.exists())
        self.assertIn("999", self.reply(send_message))  # tells them their ID, nothing else

    def test_not_relevant_is_still_published_when_you_forward_it(self, parse_post, send_message):
        parse_post.return_value = parsed(is_relevant=False)
        self.send()
        self.assertTrue(Post.objects.exists())

    def test_unknown_level_asks_to_add_it(self, parse_post, send_message):
        parse_post.return_value = parsed(year=0)
        self.send()
        self.assertFalse(Post.objects.exists())
        self.assertIn("Level", self.reply(send_message))

    @override_settings(TELEGRAM_DEFAULT_LEVEL=3)
    def test_default_level_is_used_when_missing(self, parse_post, send_message):
        parse_post.return_value = parsed(year=0)
        self.send()
        self.assertEqual(Post.objects.get().year, self.level3)

    def test_wrong_secret_in_url_or_header_is_404(self, parse_post, send_message):
        self.assertEqual(self.send(secret="nope").status_code, 404)
        self.assertEqual(self.send(header="nope").status_code, 404)
        self.assertFalse(Post.objects.exists())

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_switched_off_without_token(self, parse_post, send_message):
        self.assertEqual(self.send().status_code, 404)

    def test_help_and_empty_messages_publish_nothing(self, parse_post, send_message):
        self.send(text="/start")
        self.assertFalse(Post.objects.exists())
        self.assertIn("Forward", self.reply(send_message))

    def test_get_is_not_allowed(self, parse_post, send_message):
        url = reverse("board:telegram_webhook", args=[SECRET])
        self.assertEqual(self.client.get(url).status_code, 405)
