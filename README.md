# Group expense tracker

FastAPI + Bootstrap app: **sign in with mobile + password**, **organizations** you belong to, multiple **events** (expense pools) per organization, shared expenses and Excel export.

## What changed in v2

- **SQLite file** is now `app_data.db` (not `expense_tracker.db`). Remove the old file if you had the previous schema.
- **Auth**: register and sign in with **mobile number** (digits, 10–15) and password.
- **Organizations**: top-level “big group”; you only see orgs you are a **member** of.
- **Events**: each org hosts many events (trips, parties, rent months); each event has its own members, pool, and expenses.

## Run locally

```powershell
cd expense_tracker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000** (redirects to sign-in). API docs: **http://127.0.0.1:8000/docs**

If you see **`Router.__init__() got an unexpected keyword argument 'on_startup'`**, your environment had **Starlette 1.x** with an older **FastAPI** (before 0.135). This repo pins **FastAPI 0.136.3**, which supports Starlette 1. Run **`pip install -r requirements.txt`** in a clean venv so versions match. If the error persists, you are likely not using this venv—check `where python` / `pip show fastapi`.

Set **`SECRET_KEY`** (and optionally `SESSION_SECRET`, `JWT_SECRET`) in the environment for production.

## Web flow

1. **Register** / **Sign in** with mobile + password.
2. **Organizations** — create one; you are added automatically. Invite others by **mobile** (they must already be registered).
3. Open an organization → create **events** under it.
4. Open an **event** → balances, pool, expenses (same as before, per event).

## Android app

See **[ANDROID.md](ANDROID.md)** for opening the project in Android Studio, setting the **API base URL** (emulator vs physical device), hosting **uvicorn**, and a **manual test checklist**.

## API (mobile clients)

1. `POST /api/v1/auth/register` — body: `{ "mobile", "password", "full_name" }`
2. `POST /api/v1/auth/login` — body: `{ "mobile", "password" }` → `{ "access_token", "token_type": "bearer" }`
3. Send `Authorization: Bearer <token>` on other calls.
4. `GET /api/v1/me` — current user plus **personal totals** across all events (only where your account is linked to an event member): `total_contributed`, `total_expended`, `total_remaining` (JSON numbers).
5. `GET/POST /api/v1/organizations` — list / create (creator becomes member).
6. `POST /api/v1/organizations/{id}/members` — body `{ "mobile" }` invite.
7. `GET/POST /api/v1/organizations/{id}/events` — list / create event (`POST` body `{ "name" }`).
8. `GET /api/v1/events/{id}`, members, contributions, expenses, balances, `GET .../export.xlsx` — same behavior as the web UI, scoped to the authenticated user’s org membership.
9. **Activity / notifications** — `GET /api/v1/me/activities` (flat list), `GET /api/v1/me/activities/grouped` (organization → event → items), `POST /api/v1/me/activities/{id}/read`, `POST /api/v1/me/activities/read-all`. Scoped feeds: `GET /api/v1/organizations/{id}/activities`, `GET /api/v1/events/{id}/activities` (only if you’re allowed to view that org/event). Each activity has `read_at` (null = unread).

## Tech notes

- **Sessions** (signed cookies) for the web UI; **JWT** for the API.
- **CORS** is open for development; tighten for production.
