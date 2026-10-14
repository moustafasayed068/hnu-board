# CLAUDE.md — HNU Task & Announcement Board

Read `PLAN.md` before doing anything. It is the source of truth for scope, schema, milestones and tests.

## Project in one paragraph

A lightweight Django site for Helwan National University (HNU). Students pick their level and program (no accounts) and see assignments and announcements, deadlines first. TAs publish through Django Admin and can only edit or delete their own posts. Hosted free on PythonAnywhere with SQLite.

## How to work with me (important)

I am a CS student learning Django backend development. I want to understand and write the code myself.

- Work **one milestone at a time** (M1–M9 in `PLAN.md`). Ask which milestone we are on if unclear.
- At the start of a milestone: explain the concepts it needs in a few short paragraphs, then list the files we will touch.
- **Do not write the whole milestone for me.** Give small, explained snippets or a skeleton with TODOs; let me fill them in. Write complete code only when I explicitly ask ("write it for me").
- After I write code: review it, point out bugs or bad practice, and explain *why*.
- Write tests with me before marking a milestone done. A milestone is done only when its tests pass.
- Suggest a Git commit message at the end of each milestone.
- If something in `PLAN.md` seems wrong, say so and explain before changing direction. Don't silently redesign.

## Hard constraints

- Stack: Python, Django 5.2 LTS, Django templates, plain CSS, minimal vanilla JS. SQLite.
- Allowed dependencies: `Django`, `python-dotenv`. Ask before adding anything else.
- Do **not** add: React or any JS framework, Django REST Framework or any API, Docker, Redis, Celery, cron/background workers, caching, file uploads, student accounts, notifications.
- One Django app: `board`. Project settings package: `config`.
- All writes go through Django Admin. Public views are GET-only and read-only.
- Permissions are enforced server-side in `PostAdmin` (`get_queryset`, `has_change_permission`, `has_delete_permission`, `save_model`). Never rely on hiding buttons.
- Links: `http`/`https` only. External links use `rel="noopener noreferrer"`.
- `TIME_ZONE = "Africa/Cairo"`, `USE_TZ = True`. Always use `django.utils.timezone.now()`.
- Secrets only from environment variables / `.env`. Never commit `.env`, `db.sqlite3` or backups.

### Approved exception: WhatsApp import

The owner approved one write path outside the admin (see `PLAN.md`, "WhatsApp import"):
`board/ingest.py` (`POST /ingest/`, `GET /ingest/courses/`), guarded by the `INGEST_TOKEN`
shared secret (empty = 404). Posts are published at once, credited to the inactive
`whatsapp-bot` user, and deduplicated by `Post.source_id`. The Node bot that calls it lives
in `whatsapp-bot/` and runs on a separate server, not on PythonAnywhere. Don't add other
endpoints or dependencies on the back of this exception.

## Data model summary

`AcademicYear`, `Program`, `Course` (M2M to `Program`; empty = common course; `semester` 1 or 2), and one `Post` model with `kind` = assignment | announcement. See `PLAN.md` Part C for fields, validation rules and indexes. Public query lives in `Post.objects.visible_to(year, program)`.

Students only see and pick courses of the current semester (`board.models.current_semester()`): guessed from the date (Sep-Jan = 1, Feb-Aug = 2) unless `DJANGO_CURRENT_SEMESTER` is set to `1` or `2`.

## Seed data

`board/fixtures/hnu_courses.json` holds 4 levels, the three programs (DS, MSE, RSE) and 105 real HNU course codes/names from the August 2022 bylaws. Field names must match the models exactly (`AcademicYear.number/name`, `Program.name/slug/is_active`, `Course.code/name/year/semester/programs`). If a model field is renamed, update the fixture too. Never add student transcripts or personal data to the repo.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata hnu_courses     # after M2
python manage.py createsuperuser
python manage.py runserver
python manage.py test board
python manage.py check --deploy    # with production env vars set
```

## Style

- Clear English names, comments and docstrings. Short functions.
- Function-based views unless a class-based view is clearly simpler.
- Prefer Django built-ins over custom abstractions.
- Keep explanations concise and beginner-friendly.
