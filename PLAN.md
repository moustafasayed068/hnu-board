# HNU Task & Announcement Board — Project Plan

_As of 13 Oct 2026_

A single-app Django project for Helwan National University (HNU), where students filter a public board by level and program, and TAs publish through Django Admin with server-enforced ownership. It runs free on PythonAnywhere with SQLite.

## Key decisions at a glance

- **One app, four models** (`AcademicYear`, `Program`, `Course`, `Post`), Django 5.2 LTS, no runtime dependencies beyond `python-dotenv`.
- **One `Post` table** for assignments and announcements, so the "All" feed is one paginated query.
- **Filters live in the URL** (`/?year=3&program=ds`), so students can bookmark and share their board with no cookies or accounts.
- **Django Admin is the TA dashboard;** each TA sees and edits only their own posts.
- **No background jobs:** overdue status is computed per request; a future `published_at` doubles as scheduling.
- **Hosting:** PythonAnywhere free (persistent SQLite, no sleeping); weekly manual backup, monthly "extend" click.
- **UI:** mobile-first, using HNU's navy, light blue, orange and green as accent colours. Use the official logo only with the university's permission, as an image file they provide.

## HNU academic structure (confirmed from student transcripts)

- **Credit-hour system with Levels 1–4.** Level follows earned hours (roughly: Level 1 under ~30 h, Level 2 ~30–60 h, Level 3 ~60–100 h, Level 4 above ~100 h). Students recognise "Level 1–4", so `AcademicYear` is labelled "Level N".
- **Levels 1–2 are common.** All `BAS` (basic sciences), `COM` (computing) and `GEN` (general) courses are shared → `Course.programs` is empty.
- **Three programs: DS, MSE, RSE.** Students are assigned a program from Level 1 (faculty advisor lists), but Levels 1–2 courses are common. Program-specific courses start at Level 3 (`DSC` = Data Science). Students therefore always pick a program; common courses show for all three.
- **Terms:** Fall, Spring and a short Summer term. Mostly 3-credit courses; `GEN` courses are 2 credits.
- **Retakes are common.** Students repeat failed courses from a lower level (e.g. a Level 3 student retaking `BAS 204`). See the course filter below.
- **Course list:** 39 courses are pre-loaded in `board/fixtures/hnu_courses.json` (codes and names only, no student data). Load with `python manage.py loaddata hnu_courses` after M2's migrations.

### Schema change from the transcripts

- **Course filter works on its own.** `/?course=<id>` shows every post for that course, regardless of level or program. A student retaking a Level 2 course bookmarks that course's page alongside their level board. No new model needed; `visible_to()` is skipped when only a course is chosen.

- **Courses belong to a semester (added after the bylaws were read).** `Course.semester` is 1 or 2. Students can only pick, and only see posts for, courses of the current semester. The current semester is guessed from the date (Sep–Jan = 1, Feb–Aug = 2) and can be forced with `DJANGO_CURRENT_SEMESTER`. The fixture now holds 105 courses for all three programs, Levels 1–4, taken from article 27 of the August 2022 bylaws.

### Still to confirm (none block M1–M2)

1. **Full names of MSE and RSE, and their Level 3–4 courses** — the fixture uses the codes as placeholder names. Rename and add courses in admin; no code change.
2. **Level 4 courses** — not in the transcripts yet (Fall 2026 grades not posted). Add them in admin as they start.
3. **Edge cases in the fixture:** `BAS 203` (Fundamentals of Management) and `GEN 115` (Professional Ethics) are set to Level 1 because students took them then; `GEN 317` is set to Level 3 and common. Adjust in admin if wrong.
4. **Can any TA post to any course?** Default yes (edits limited to own posts). To restrict TAs to assigned courses, add a `Course.tas` many-to-many.
5. **Other faculties?** Out of scope for launch; adding a `Faculty` model above `Program` later is a small migration.

---

## Part A — Product Analysis

A public, read-only notice board filtered by level and program, plus a locked-down admin where TAs write posts. Students miss assignments because information is scattered across WhatsApp/Telegram groups and LMS pages; this gives one URL per level + program that always shows what is due next.

### Essential user journeys

1. **Student, first visit:** opens site → picks level → picks program → sees "Due soon" assignments first, then recent posts → taps an assignment → opens the resource or submission link.
2. **Student, return visit:** opens a bookmarked URL like `/?year=2&program=ds` and lands on their filtered board. The filter lives in the URL, so it is shareable in the class group.
3. **Student, narrowing:** filters by course, or switches between All / Assignments / Announcements.
4. **TA, publishing:** logs in at `/manage/` → Add post → picks course and audience → sets deadline → saves. It appears immediately (or at the publication date).
5. **TA, correcting:** edits the deadline of their own post; cannot see or save changes to another TA's post.
6. **Admin (you):** creates TA accounts, maintains levels, programs and courses, and can fix any post.

### Smallest useful MVP

One public board page with filters, one post detail page, and Django Admin for writing.

### Risks and missing requirements

- **Adoption is the real risk.** Get 2–3 TAs committed before launch and post the URL in existing groups.
- **Stale deadlines.** Show "Updated <date>" on edited posts.
- **Who can post for which course?** Default: any TA posts anywhere, edits only their own.
- **Announcement audience.** May target a whole level, a program, or one course. The schema handles all three.
- **Unsafe links.** Block non-http(s) URLs such as `javascript:`.
- **University approval.** Check permission to use the HNU name and logo.

---

## Part B — Architecture

One Django project with one app, `board`. Students use two public views; TAs use Django Admin. No API, no JS framework, no background worker.

### Project structure

```
hnu-board/
├── config/                 # project settings package
│   ├── settings.py         # reads secrets from environment variables
│   ├── urls.py
│   └── wsgi.py
├── board/                  # the only app
│   ├── models.py           # AcademicYear, Program, Course, Post
│   ├── admin.py            # TA publishing + ownership rules
│   ├── forms.py            # BoardFilterForm (validates ?year=&program=&course=&type=)
│   ├── views.py            # board_list, post_detail
│   ├── urls.py
│   ├── templates/board/    # base.html, list.html, detail.html, _post_card.html
│   ├── static/board/       # site.css, filter.js
│   ├── migrations/
│   └── tests/              # test_models.py, test_views.py, test_admin.py, test_settings.py
├── requirements.txt        # Django, python-dotenv
├── .env.example            # variable names, no real values
├── .gitignore              # .env, db.sqlite3, staticfiles/, __pycache__/, backups
├── CLAUDE.md
├── PLAN.md
└── manage.py
```

**Why one app:** academic structure and posts change together and are tiny. Splitting adds cross-app imports and migration ordering for no benefit.

### Responsibilities

| Part | Responsibility |
| --- | --- |
| `models.py` | Data shape, validation (`clean()`), public queryset (`Post.objects.visible_to(...)`) |
| `forms.py` | Turns untrusted query-string values into validated model instances |
| `views.py` | Read-only pages; no writes, no login |
| `admin.py` | All writing; enforces ownership on the server |
| Templates | Rendering only; Django auto-escapes all post text |

### Request flow — student viewing assignments

1. Browser requests `GET /?year=3&program=ds&type=assignment`.
2. `board_list` binds `BoardFilterForm(request.GET)`. Invalid or missing values → show the selector, not an error.
3. View builds two querysets with `select_related("course", "year", "program")`: **Due soon** (assignments with deadline ≥ now, nearest first) and **Recent posts** (everything else, newest first).
4. Recent posts go through `Paginator` (20 per page). About 3–4 SQL queries per page.
5. Template renders cards; deadlines in Cairo time with a "Due in 2 days" or "Closed" badge.

### Request flow — TA publishing an assignment

1. TA opens `/manage/` (admin mounted at a less-guessable path) and logs in. Django checks the password hash and `is_staff`.
2. Admin checks `board.add_post` (granted through a "Teaching assistants" group).
3. Django validates fields and runs `Post.clean()`.
4. `PostAdmin.save_model()` sets `created_by = request.user` on create only. The field is never in the form.
5. Post appears publicly once `published_at` ≤ now.

### Public reads + authenticated writes

- **Public views never write** (GET only) → no student-facing forms to abuse.
- **All writes go through admin:** login, `is_staff`, model permissions, CSRF by default.
- **Object-level rule:** `PostAdmin.get_queryset()` returns only the TA's own posts (superusers see all). Another TA's post is invisible and its edit URL returns "not found". `has_change_permission(obj)` / `has_delete_permission(obj)` repeat the check and cover bulk "delete selected".
- **Academic data is admin-only.** TAs get *view* permission on levels, programs and courses.

---

## Part C — Database Design

Four models. TA ownership uses Django's built-in `User` plus one foreign key.

### ER diagram (text)

```
AcademicYear 1 ──< Course >──< Program        (Course.programs: many-to-many, empty = common)
AcademicYear 1 ──< Post
Program      1 ──< Post   (optional; empty = whole level)
Course       1 ──< Post   (optional for announcements, required for assignments)
User         1 ──< Post   (created_by, on_delete=PROTECT)
```

### Key decisions

- **One `Post` model, not two:** one ordered, paginated query for the "All" feed. Assignment-only fields are nullable and enforced by validation + a DB constraint.
- **"Program", not "Department":** matches how HNU is organised. Rename freely.
- **Shared courses:** `Course.programs` many-to-many; empty = common course for every program in that level.
- **Explicit audience:** every post has a `year`; `program` optional; `course` required for assignments. When a course is chosen, `clean()` copies its year.
- **Deleting a TA never deletes posts:** `created_by` uses `PROTECT`; deactivate accounts instead.
- **No `status` field:** upcoming / due soon / closed are computed from `deadline` vs now.
- **Free scheduling:** a future `published_at` hides a post until then.

### Models and fields

| Model | Fields | Notes |
| --- | --- | --- |
| `AcademicYear` | `number` (small int, unique), `name` ("Level 3") | Ordered by `number` |
| `Program` | `name`, `slug` (unique), `is_active` | Slug in URLs: `?program=ds` |
| `Course` | `code` (unique), `name`, `year` → AcademicYear, `programs` ↔ Program (blank) | Shared or common courses |
| `Post` | `kind`, `title`, `body`, `year` → AcademicYear, `program` → Program (null), `course` → Course (null), `resource_url`, `submission_url`, `deadline` (null), `published_at`, `notes`, `created_by` → User, `created_at`, `updated_at` | One table for both kinds |

### Validation rules on `Post`

- Assignment → `course` and `deadline` required (`clean()` and a `CheckConstraint`).
- URLs → `URLField` with a validator limited to `http` and `https`.
- Course given → `year` must equal `course.year`; `program`, if given, must be one of the course's programs (or the course is common).
- Deadline before `published_at` → validation error.

### Indexes

```python
class Meta:
    ordering = ["-published_at"]
    indexes = [
        models.Index(fields=["year", "-published_at"]),  # Recent posts feed
        models.Index(fields=["year", "deadline"]),       # Due-soon list
    ]
```

### The public query, in words

For level *Y* and program *P*: year is *Y*; program is *P* or empty; course is empty or offered to *P* (or common); `published_at` ≤ now. Implement once as `Post.objects.visible_to(year, program)`. Use a subquery of course IDs rather than an M2M join, to avoid duplicates and `distinct()`.

---

## Part D — Implementation Plan

Commit to Git at the end of every milestone; don't start the next until its tests pass.

### M1 — Project setup
- **Objective:** running empty project, safe settings from day one.
- **Concepts:** virtualenvs, `startproject`/`startapp`, settings, env vars, `.gitignore`.
- **Files:** `config/settings.py`, `.env.example`, `.gitignore`, `requirements.txt`.
- **Do:** Django 5.2 LTS; `TIME_ZONE = "Africa/Cairo"`, `USE_TZ = True`; `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` from env (`DEBUG` off unless `"1"`).
- **Done when:** `runserver` works; `.env` and `db.sqlite3` untracked.
- **Test:** `python manage.py check` passes.

### M2 — Models and migrations
- **Objective:** the four models with validation.
- **Concepts:** `ForeignKey` vs `ManyToManyField`, `on_delete`, `TextChoices`, `clean()`, `CheckConstraint`, `Meta.indexes`, custom managers.
- **Files:** `board/models.py`, `board/migrations/`.
- **Done when:** migrations apply; `visible_to()` exists.
- **Tests:** assignment without deadline fails; `javascript:` URL fails; course/year mismatch fails; `visible_to()` correct for common and shared courses.

### M3 — Admin for academic structure
- **Objective:** manage levels, programs, courses in the browser.
- **Concepts:** `ModelAdmin`, `list_display`, `search_fields`, `prepopulated_fields`, `filter_horizontal`, fixtures.
- **Files:** `board/admin.py`, `board/fixtures/hnu_courses.json` (provided).
- **Done when:** `loaddata hnu_courses` works and the 39 courses show in admin.
- **Test:** admin changelists return 200 for a superuser.

### M4 — TA publishing and ownership
- **Objective:** TAs create/edit/delete only their own posts.
- **Concepts:** groups, model permissions, `is_staff`, `get_queryset`, `has_change_permission`, `has_delete_permission`, `save_model`, `readonly_fields`, `autocomplete_fields`.
- **Files:** `board/admin.py`; "Teaching assistants" group via a data migration.
- **Done when:** TA A cannot see, open, edit or delete TA B's post, even by URL.
- **Tests:** Part F, TA permissions.

### M5 — Public board view and filter form
- **Objective:** `/` shows a selector; `/?year=&program=` shows the board.
- **Concepts:** function-based views, `forms.Form`, `ModelChoiceField(to_field_name=...)`, GET forms, `select_related`.
- **Files:** `board/forms.py`, `board/views.py`, `board/urls.py`.
- **Done when:** invalid query values show the selector, never a 500.
- **Tests:** filtering by year, program, course and type.

### M6 — Deadlines, sorting, pagination
- **Objective:** "Due soon" first, then the paginated recent feed.
- **Concepts:** `timezone.now()`, aware datetimes, `Paginator`, model properties (`is_overdue`, `is_due_soon`).
- **Done when:** upcoming nearest-first; closed assignments stay visible, marked "Closed".
- **Tests:** sorting, overdue boundary, page size.

### M7 — Templates and mobile UI
- **Objective:** readable, mobile-first board in HNU colours.
- **Concepts:** template inheritance, `{% include %}`, `date`/`timeuntil` filters, `linebreaksbr`, static files.
- **Files:** `base.html`, `list.html`, `_post_card.html`, `site.css`, `filter.js` (auto-submit on change; works without JS).
- **Done when:** usable at 360 px; assignment and announcement cards visually distinct.
- **Test:** response contains selected level/program names and deadline text.

### M8 — Detail page, links and hardening
- **Objective:** detail page with safe external links; production settings.
- **Concepts:** `get_object_or_404`, `rel="noopener noreferrer"`, `SECURE_*` settings, `check --deploy`.
- **Done when:** future-dated posts 404; `check --deploy` clean with production env.
- **Tests:** missing submission URL, unpublished post 404, deploy-settings test.

### M9 — Deploy
- **Objective:** live on PythonAnywhere with HTTPS and a backup routine.
- **Concepts:** WSGI, `collectstatic`, env vars on the host, production migrations.
- **Done when:** a TA posts from a phone and a student sees it on a phone over HTTPS.
- **Test:** run the full suite in the server console before going live.

---

## Part E — Deployment

**Recommendation: PythonAnywhere free Beginner account + SQLite.** Persistent disk, no sleeping, free HTTPS, no credit card. Cost: a monthly click to extend the web app. Limits checked 13 Oct 2026; nothing is guaranteed to stay free.

| | PythonAnywhere Beginner | Render Free |
| --- | --- | --- |
| Web app | 1 app, 1 worker, `username.pythonanywhere.com` only | 512 MB RAM, 0.1 CPU |
| Sleeping | No | Spins down after 15 min idle; ~1 min to wake |
| Storage | 512 MB persistent | Ephemeral — SQLite wiped on restart/deploy |
| Database | SQLite (no MySQL for accounts created after 15 Jan 2026) | Free Postgres 1 GB, expires after 30 days (+14-day grace), no backups |
| Upkeep | Web app expires after 1 month unless extended (data kept) | Recreate DB monthly or pay |
| Other | Restricted outbound internet, no SSH, no scheduled tasks | 750 free instance hours/month |
| Cheapest paid | $10/month | ~$7/month (third-party figure) |

**Why SQLite is fine:** read-heavy, few writers, one worker. Switching to PostgreSQL later needs no code changes.

### Production settings

```python
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
STATIC_ROOT = BASE_DIR / "staticfiles"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 3600   # raise once stable
```

### Steps on PythonAnywhere

1. Push the repo to GitHub (no secrets or DB in it).
2. Bash console: clone, create a virtualenv, `pip install -r requirements.txt`.
3. Create `.env` with the three `DJANGO_*` variables; load it in the WSGI file with `python-dotenv`.
4. `migrate`, `createsuperuser`, `collectstatic`.
5. Web tab: point at `config/wsgi.py` and the virtualenv; map `/static/` → `staticfiles/`; turn on **Force HTTPS**.
6. Reload; run `python manage.py check --deploy`.
7. Updates: `git pull` → `migrate` → `collectstatic` → Reload.

### Backups

- **Weekly:** `python manage.py dumpdata board auth.user auth.group --indent 2 > backup-YYYY-MM-DD.json`, download from the Files tab.
- Never commit backups (they contain password hashes).
- **Monthly:** click "extend" on the Web tab; set a phone reminder.

---

## Part F — Testing

Django `TestCase` + test `Client`, no extra libraries. Control time with deadlines relative to `timezone.now()` (e.g. now ± 1 minute).

| Area | Test | Expected |
| --- | --- | --- |
| Filtering | Level 3 + CS shows CS, level-wide and common-course posts | Present |
| Filtering | Level 3 + CS hides IS-only and level 2 posts | Absent |
| Filtering | Shared course (CS + AI) post | Appears once for each program |
| Filtering | `?year=abc` or unknown program | 200 with selector, not 500 |
| Filtering | `?type=assignment` | Only assignments |
| Filtering | `?course=<BAS 204 id>` alone (retake case) | All BAS 204 posts, any level |
| Sorting | Three upcoming deadlines, random order | Nearest first |
| Sorting | Recent feed | Newest first; 20 per page |
| Expired | Deadline 1 minute ago | Not in "Due soon"; "Closed" in feed |
| Expired | Deadline in 1 minute | In "Due soon" |
| Publication | `published_at` tomorrow | Hidden; detail 404 |
| Missing submission URL | Empty `submission_url` | Renders; no empty link; clear text |
| TA login | Anonymous `GET /manage/board/post/add/` | Redirect to login |
| TA login | Logged-in non-staff | Denied |
| TA permissions | TA creates a post with forged `created_by` | `created_by` = that TA |
| Unauthorized edit | TA A opens TA B's change URL | Not found; unchanged |
| Unauthorized delete | TA A deletes B's post (URL and bulk action) | Post still exists |
| Unauthorized edit | TA changes a Course | 403 |
| Admin override | Superuser edits any post | Allowed |
| Unsafe input | `javascript:alert(1)` URL | Validation error |
| Unsafe input | `<script>` in title/body | Escaped |
| Unsafe input | Assignment without deadline/course | Validation error + DB constraint |
| Unsafe input | Level 2 course on level 3 post | Validation error |
| Production | `DJANGO_DEBUG` unset | `DEBUG is False` |
| Production | `check --deploy` with production env | No warnings |
| Production | Public page HTML | No admin links |

Run `python manage.py test board` before every commit.

---

## WhatsApp import (added after MVP)

The faculty posts assignments for all four levels in one WhatsApp channel. A bot copies them to the board.

- **Flow:** `whatsapp-bot/` (Node + Baileys, on a free Oracle Cloud VM, spare number) → Cohere LLM extracts kind, level, course code, deadline, links → `POST /ingest/` with header `X-Ingest-Token` → `board/ingest.py` validates with `full_clean()` and publishes.
- **Why an endpoint:** WhatsApp has no official API for channels, so something outside PythonAnywhere must read them and hand the posts over. One token-protected view is the smallest way to do that.
- **Repairs instead of rejecting:** invalid links are dropped, a program the course isn't offered to becomes the whole level, and an assignment without a course or valid deadline becomes an announcement. Only a message whose level can't be found is refused (422).
- **Duplicates:** `Post.source_id` (`<channel>:<message id>[:<program>]`, unique).
- **Risk:** Baileys is unofficial; the spare number can be banned. Setup and recovery: `whatsapp-bot/SETUP.md`.
- **Tests:** `board/tests/test_ingest.py`.

## Telegram import (added after the WhatsApp import)

The WhatsApp bot only runs while the owner's PC is on. To publish from the phone at any time, the owner forwards (or pastes) a channel post to a private Telegram bot.

- **Flow:** Telegram → `POST /telegram/<secret>/` on PythonAnywhere (`board/telegram.py`) → Cohere (`board/llm.py`, the Python twin of `whatsapp-bot/parser.js`, standard library only) → `ingest.publish()` → reply in Telegram ("Published: …", "Already on the board", "Couldn't tell the level").
- **Security:** switched off (404) unless `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` are set; the secret must match in the URL and in Telegram's `X-Telegram-Bot-Api-Secret-Token` header; only user IDs in `TELEGRAM_ALLOWED_USER_IDS` can post.
- **Duplicates across both imports:** `Post.text_hash` = SHA-256 of the message text with spaces, case and `*_~` formatting removed. `/ingest/` and the webhook refuse a post whose `source_id` **or** `text_hash` already exists, and the WhatsApp bot asks first (`check_only`) so a post forwarded earlier costs no LLM call. Limit: an edited text is a new post.
- **Tags override the LLM:** `#L1`–`#L4`, `#ds #mse #rse` / `#all`, `#<coursecode>` (e.g. `#DSC411`), `#assignment` / `#announcement`. Tags are removed before the LLM call and the fingerprint. An unknown course tag publishes nothing. The reply lists what was saved with an admin edit link. Replying to that message with tags only (`#L3`, `#DSC301`, `#mse`, `#all`, `#assignment`, `#delete`) fixes or deletes those posts; only posts made by the import can be changed this way.
- **Forwarded = relevant:** the LLM's `is_relevant` is ignored for Telegram; a missing level uses `TELEGRAM_DEFAULT_LEVEL`, else the post is refused with a hint.
- **Approved by the owner on 19 Oct 2026** as a second exception to "all writes go through Django Admin".
- **Tests:** `board/tests/test_telegram.py`, `board/tests/test_ingest.py`.

## Optional later improvements (not MVP)

| Improvement | Add it when |
| --- | --- |
| Login rate limiting (`django-axes`) | Admin is public beyond a pilot |
| `Course.tas` restriction | TAs post to wrong courses |
| `Faculty` model | A second faculty joins |
| Arabic interface (i18n, RTL) | Students or TAs ask for it |
| RSS/iCal feed per board | Students want calendar reminders |
| Per-view caching | Pages measurably slow |
| PostgreSQL | Moving to a host with a durable DB |
| Custom domain | University provides one (paid PythonAnywhere plan) |

## Sources

- [PythonAnywhere — Plans and pricing](https://www.pythonanywhere.com/pricing/)
- [PythonAnywhere — Free accounts features](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/)
- [PythonAnywhere blog — Changes on free accounts (2026)](https://blog.pythonanywhere.com/221/)
- [Render — Deploy for free](https://render.com/docs/free)
