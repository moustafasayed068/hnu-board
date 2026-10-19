"""Re-check the level of posts the imports already published, and fix wrong ones.

Before 19 Oct 2026, posts whose level the AI couldn't tell were put in Level 4 (the channel
default). This asks the AI again (one Cohere call per message) and moves each message to the
levels it is really for, or to every level when it is for all students.

    python manage.py fix_import_levels            # show the plan, change nothing
    python manage.py fix_import_levels --apply    # do it

Posts with a course are skipped: their level comes from the course, so it is already right.
"""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from board.ingest import bot_user, level_numbers, message_source_id, rebuild_copies
from board.llm import parse_post
from board.models import AcademicYear, Course, Post


class Command(BaseCommand):
    help = "Re-check and fix the levels of imported posts (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Change the posts (default: only show).")
        parser.add_argument("--limit", type=int, default=200, help="Max messages to check (LLM calls).")

    def handle(self, *args, apply=False, limit=200, **options):
        all_levels = list(AcademicYear.objects.order_by("number"))
        courses = [
            {"code": c.code, "name": c.name, "level": c.year.number}
            for c in Course.objects.current().select_related("year")
        ]
        groups = defaultdict(list)  # one entry per imported message (all its copies)
        posts = (Post.objects.filter(created_by=bot_user(), course__isnull=True)
                 .select_related("year", "program").order_by("pk"))
        for post in posts:
            groups[message_source_id(post.source_id) or f"post:{post.pk}"].append(post)

        checked = changed = 0
        for key, copies in list(groups.items())[:limit]:
            first = copies[0]
            current = sorted({p.year.number for p in copies})
            text = f"{first.title}\n\n{first.body}".strip()
            data = parse_post(text, first.published_at, courses)
            checked += 1
            numbers = sorted(level_numbers(data)) or [lv.number for lv in all_levels]
            if numbers == current:
                continue
            changed += 1
            label = "all levels" if len(numbers) == len(all_levels) else ", ".join(f"L{n}" for n in numbers)
            self.stdout.write(f"#{first.pk} {first.title[:60]!r}: L{','.join(map(str, current))} -> {label}")
            if apply:
                years = [lv for lv in all_levels if lv.number in numbers]
                try:
                    rebuild_copies(copies, years=years)
                except ValidationError as error:
                    self.stderr.write(f"  could not fix: {error.messages}")

        verb = "Fixed" if apply else "Would fix"
        self.stdout.write(self.style.SUCCESS(f"Checked {checked} messages. {verb} {changed}."))
        if not apply and changed:
            self.stdout.write("Run again with --apply to make these changes.")
