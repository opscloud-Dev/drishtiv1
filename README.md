# Drishti API — Python backend

FastAPI + PostgreSQL. Handles accounts (email + password), children, the
teacher directory, bookings, and the mentor verification workflow.

Tested with Python 3.12, PostgreSQL 16, FastAPI 0.141, SQLAlchemy 2.1,
bcrypt 5, PyJWT 2.15 (what `pip install -r requirements.txt` resolves today).
56 automated tests cover it (see "Running the tests").

---

## Upgrading from the previous version — READ THIS FIRST

This version replaces the old "device ID" identity with **real accounts**
(email + password). The `parents` and `mentors` tables changed shape, and
SQLAlchemy can't alter existing tables — so an old database will not work.

```bash
python -m app.reset_db
```

This **deletes all data** (asks you to type `yes`), rebuilds every table, and
reseeds the 5 sample teachers. If you forget, the API refuses to start and
prints this exact instruction, rather than failing later with confusing 500s.

Phones that were signed in under the old version simply land on the intro
screen — no need to delete the app.

---

## Part 1 — Run it locally (~10 minutes)

You need Python 3.10+ and PostgreSQL.

```bash
brew install postgresql@16          # skip if you have Postgres
brew services start postgresql@16
createdb drishti

cd drishti_backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a file named `.env` in this folder (copy `.env.example`):

```
DATABASE_URL=postgresql://YOUR_MAC_USERNAME@localhost:5432/drishti
JWT_SECRET=<paste a generated secret>
```

Generate the secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

`JWT_SECRET` signs everyone's login tokens. Keep it private. If it is missing,
a temporary one is used and **everybody is logged out every time the server
restarts**. If it is set but shorter than 32 characters, the server refuses to
start.

Start the server:

```bash
uvicorn app.main:app --reload
```

Tables are created automatically on first start. Load the sample teachers:

```bash
python -m app.seed
```

Check it: open http://127.0.0.1:8000/docs — FastAPI's interactive explorer.
(Use the padlock button there and paste a token to try protected endpoints.)

**Testing on a real phone?** Start with `--host 0.0.0.0` so your phone can
reach it, and put your Mac's LAN IP (`ipconfig getifaddr en0`) in the Flutter
app's `lib/config.dart`:

```bash
uvicorn app.main:app --reload --host 0.0.0.0
```

---

## Part 2 — Approving a mentor

A mentor's lifecycle, as the app shows it:

| Status | Meaning | How it gets there |
|---|---|---|
| **Pending verification** | Account exists, profile not filled in | Mentor signs up |
| **Under review** | Credential, experience and bio submitted | Mentor taps "Submit for review" |
| **Verified** | Bookable; real dashboard unlocked | You approve them (below) |

```bash
python -m app.admin list-mentors
python -m app.admin approve-mentor radhika@example.com --slots 5
```

`approve-mentor` creates the mentor's public teacher profile from what they
submitted and links it. Options:

- `--slots N` — adds N placeholder daily slots (10:00 UTC, from tomorrow) so
  they're bookable immediately. **These are placeholder times** — edit the
  `teacher_slots` table for real availability.
- `--institution "Kerala Kalamandalam"` — the text in the green "verified"
  badge parents see (defaults to what the mentor typed as their credential).
- `--force` — approve even if they haven't submitted a profile yet.

**Nothing notifies the mentor.** The app tells them "we'll notify you", so
message them yourself (email/WhatsApp) when you approve.

## Resetting someone's password

There is no "forgot password" email yet. When a tester is locked out:

```bash
python -m app.admin set-password parent devika@example.com
```

It prompts for the new password (so it never lands in your shell history).

---

## Part 3 — Deploying (so testers' phones can reach it)

**Render.com** (free tier for the API and a small Postgres):

1. Push this folder to a GitHub repo.
2. Render: **New → Web Service**, connect the repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **New → PostgreSQL**; copy its **Internal Database URL**
   (`postgres://…` and `postgresql://…` both work).
4. In the Web Service's **Environment** tab add:
   - `DATABASE_URL` = that URL
   - `JWT_SECRET` = a generated secret (command above)
5. Deploy, then in Render's Shell tab: `python -m app.seed`
6. Put the public URL (`https://….onrender.com`) in the Flutter app's
   `lib/config.dart` and rebuild.

Free-tier services go to sleep when idle: the **first request after a quiet
spell can take up to a minute**. Testers will see a spinner, not an error —
the app waits up to 45 seconds. Worth telling them.

---

## Running the tests

They run against a real Postgres and **wipe it**, so use a dedicated database.
(The suite refuses to run unless the database name contains "test".)

```bash
createdb drishti_test
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql://YOUR_MAC_USERNAME@localhost:5432/drishti_test pytest
```

They cover signup/login, token handling (expired, forged, deleted account),
per-user access rules, booking (including two parents grabbing the same slot
at the same instant), cancellation, the mentor lifecycle, and the admin
commands.

---

## API at a glance

`Auth` column: who may call it. Identity always comes from the token — a
parent can only ever touch their own children and bookings, a mentor only
their own profile and classes.

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /auth/signup/parent` | – | name, email, password → token |
| `POST /auth/signup/mentor` | – | + art form → token |
| `POST /auth/login` | – | role, email, password → token |
| `GET /teachers` | – | directory with open, upcoming slots |
| `GET /parents/{id}/children` · `POST /children` | parent (self) | children |
| `POST /bookings` · `PATCH /bookings/{id}/cancel` | parent | book / cancel |
| `GET /parents/{id}/bookings` | parent (self) | my bookings |
| `GET /mentors/{id}` · `PUT /mentors/{id}/profile` | mentor (self) | profile & "submit for review" |
| `GET /teachers/{id}/stats` · `/bookings` | verified mentor (own) | dashboard data |

---

## Before a public launch

Fine for a closed test group; not yet for the public:

- **No "forgot password" email flow** (use `set-password` above).
- **No rate limiting** on login/signup, so passwords could be guessed
  repeatedly. Add it (or put the API behind a service that does).
- **"Continue with Google" is not implemented** — the button is a placeholder.
  It needs a Google Cloud project and OAuth client IDs.
- **Login tokens last 30 days** and can't be revoked individually.
- **"Attendance rate" is a stand-in.** There is no attendance tracking; it's
  the share of past scheduled classes that weren't cancelled (blank until a
  mentor has any history).
- **Recording consent was removed from signup**, as the new mockup has no such
  step. The `consent_recording` column still exists. Add a consent step back
  before any class is recorded.
- **Slots are added by you** (SQL or `--slots`); mentors can't yet manage their
  own availability.
