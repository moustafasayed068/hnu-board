from io import StringIO
from unittest import mock

from django.core.management import call_command

from board.ingest import bot_user
from board.models import Post

from .base import BoardTestCase


def answer(years):
    return {"is_relevant": True, "kind": "announcement", "title": "", "body": "",
            "years": years, "programs": [], "course_code": "", "course_hint": "",
            "deadline": "", "submission_url": "", "resource_url": ""}


@mock.patch("board.management.commands.fix_import_levels.parse_post")
class FixImportLevelsTests(BoardTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("fix_import_levels", *args, stdout=out)
        return out.getvalue()

    def imported(self, title, **fields):
        return self.make_post(title, created_by=bot_user(), **fields)

    def test_dry_run_changes_nothing(self, parse_post):
        parse_post.return_value = answer([2])
        self.imported("Wrong level", source_id="chan:1")
        out = self.run_command()
        self.assertIn("L3 -> L2", out)
        self.assertEqual(Post.objects.get().year, self.level3)

    def test_apply_moves_to_the_right_level_or_all_levels(self, parse_post):
        self.imported("For level 2", source_id="chan:1")
        self.imported("For everyone", source_id="chan:2")
        parse_post.side_effect = [answer([2]), answer([])]
        self.run_command("--apply")
        self.assertEqual(Post.objects.get(title="For level 2").year, self.level2)
        self.assertEqual(set(Post.objects.filter(title="For everyone").values_list("year__number", flat=True)),
                         {2, 3})

    def test_right_level_course_posts_and_ta_posts_are_left_alone(self, parse_post):
        parse_post.return_value = answer([3])
        self.imported("Already right", source_id="chan:1")
        self.imported("Has a course", source_id="chan:2", course=self.retake)
        self.make_post("TA post")
        out = self.run_command("--apply")
        self.assertIn("Fixed 0", out)
        self.assertEqual(parse_post.call_count, 1)  # only the course-less import was checked
