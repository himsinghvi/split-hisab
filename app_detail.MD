# Group Expense Tracker — Application Specification

> **Purpose:** Complete reference for building the mobile app against the existing FastAPI backend. Describes domain model, money logic, screens, flows, API, permissions, and edge cases as implemented in the web app (v2) and `/api/v1`.

---

## 1. Product overview

**Group Expense Tracker** (package name on Android: `com.splitt.expense`) helps groups track shared money across trips, parties, rent cycles, etc.

| Layer | Description |
|--------|-------------|
| **User** | Registered person (mobile + password). |
| **Organization** | Long-lived group (family, team). Users only see orgs they belong to. |
| **Event** | One occasion under an org (e.g. “Ski trip March”). Has its own member list and expense log. |
| **Expense** | A bill with a total and per-member splits. |
| **Org finances** | Shared purse deposits + bill-front credits + per-person settlement across **all events** in the org. |

**Currency:** Indian Rupee (₹) in UI; amounts stored as `Numeric(12,2)` / JSON decimals with 2 decimal places.

**Backend:** FastAPI 2.0, SQLAlchemy, SQLite locally (`app_data.db`) or Postgres on Vercel (`DATABASE_URL`).

**Clients:**
- **Web:** Session cookies (`/auth/*`, HTML forms).
- **Mobile / API:** JWT Bearer token (`/api/v1/*`).

**API base URL (mobile):** `{host}/api/v1/` (trailing slash optional; Retrofit paths are relative, e.g. `auth/login`).

---

## 2. Domain hierarchy

```
User
 └── OrganizationMember (org roster — registered users only)
      └── Organization
           ├── OrganizationContribution (shared purse + bill-front credits)
           ├── Event
           │    ├── Member (event participant — may or may not link to User)
           │    └── Expense
           │         └── ExpenseSplit (member_id + amount)
           └── Activity (notifications, per recipient)
```

**Access rule:** Any org member can view and edit **all events** under that organization. Event access = org membership (`user_can_access_event`).

**Two member concepts:**
- **Organization member** (`OrganizationMember`): must be a registered user; invited by mobile.
- **Event member** (`Member`): display name on splits; optionally linked to `user_id`. Can be added from org roster, by mobile, or as name-only (no account).

---

## 3. Money model (critical for mobile)

### 3.1 Two types of org “pool” credits

All credits live in `organization_contributions`, distinguished by `expense_id`:

| Type | `expense_id` | How created | Counts toward shared purse? |
|------|--------------|-------------|------------------------------|
| **Shared purse deposit** | `NULL` | Manual “Add deposit” on org Finances | **Yes** |
| **Bill-front credit** | set (unique per expense) | Auto when an expense is saved | **No** |

### 3.2 Key formulas

**Organization total expenditure** (shown as single stat on org Finances page):

```
total_expenditure = SUM(expense.amount_total) for all events in org
```

**Event total expenditure** (shown on event page):

```
total_expenditure = SUM(expense.amount_total) for that event only
```

**Shared purse received (org):**

```
manual_pooled_total = SUM(contribution.amount WHERE expense_id IS NULL)
```

**Unspent shared purse (API field `pool_available`; not shown on simplified org web UI but available via API):**

```
pool_available = manual_pooled_total - total_expenditure
```

**Per org roster user** (`GET /organizations/{id}/balances`):

| Field | Meaning |
|-------|---------|
| `manual_contributed` | Their shared purse deposits |
| `expense_front_pool` | Bills they fronted (expense-linked credits) |
| `contributed` | `manual_contributed + expense_front_pool` |
| `expended` | Sum of **split lines** across all events in org where their event member rows link to this `user_id` |
| `remaining` | **Settlement** = `contributed - expended` |

Positive settlement ≈ net credit (others owe them); negative ≈ they owe the group.

**Per event member** (`GET /events/{id}/balances`):

| Field | Meaning |
|-------|---------|
| `expended` | Sum of split amounts for that member on **this event only** |
| `manual_contributed`, `expense_front_pool`, `contributed`, `remaining` | Always **0** at event level (org-level only) |

**Current user global summary** (`GET /me`):

| Field | Meaning |
|-------|---------|
| `total_manual_contributed` | Shared purse deposits credited to them (all orgs) |
| `total_expense_pool_credited` | Bill-front credits (all orgs) |
| `total_contributed` | Sum of both |
| `total_expended` | Sum of splits on any event member row linked to their account |
| `total_remaining` | `total_contributed - total_expended` |

### 3.3 Bill-front (who paid the card)

When an expense is created/updated:

1. Full bill total is recorded as an `OrganizationContribution` with `expense_id` set.
2. Credited to **pool creditor**:
   - `pool_creditor_member_id` (API/web) → that event member’s `user_id`, **or**
   - `pool_credit_user_id` (API only), **or**
   - Default: user who created the expense (`created_by_user_id`).
3. Creditor must be on org roster and (for member-based pick) on a split line with a linked account.

**Bill-front lines cannot** be edited/deleted via contribution endpoints — change the expense instead.

---

## 4. Data model (database)

### 4.1 `users`

| Column | Type | Notes |
|--------|------|-------|
| id | PK | |
| mobile | string, unique | Normalized to digits only, 10–15 chars |
| password_hash | string | bcrypt |
| full_name | string | max 120 |
| created_at | datetime | UTC |

### 4.2 `organizations`

| Column | Notes |
|--------|-------|
| id, name | max 200 chars |
| created_by_user_id | FK users, nullable |
| created_at | |

### 4.3 `organization_members`

| Column | Notes |
|--------|-------|
| organization_id, user_id | unique together |
| created_by_user_id | who invited |
| created_at | |

### 4.4 `organization_contributions`

| Column | Notes |
|--------|-------|
| organization_id, user_id | who the credit is **for** |
| amount | > 0 |
| note | optional text |
| created_by_user_id | who logged it |
| expense_id | NULL = manual purse; set = bill-front (1:1 with expense) |
| created_at | |

### 4.5 `events`

| Column | Notes |
|--------|-------|
| organization_id | |
| name | max 200 |
| created_by_user_id | |
| created_at | |

Creating an event **auto-adds** the creator as an event member (linked to their user).

### 4.6 `members` (event members)

| Column | Notes |
|--------|-------|
| event_id | |
| name | display on splits, max 120 |
| user_id | optional FK users |
| created_by_user_id | |
| created_at | |

### 4.7 `expenses`

| Column | Notes |
|--------|-------|
| event_id | |
| title, category | max 200 / 100 |
| amount_total | bill total |
| expense_date | date |
| created_by_user_id | |
| pool_credit_user_id | optional override for bill-front recipient |
| created_at | |

### 4.8 `expense_splits`

| Column | Notes |
|--------|-------|
| expense_id, member_id | |
| amount | that member’s share |

### 4.9 `activities`

Per-recipient notification rows.

| Column | Notes |
|--------|-------|
| recipient_user_id | |
| organization_id, event_id | optional scope |
| actor_user_id | |
| kind | string slug (see §10) |
| summary | max 500 chars; may differ per recipient |
| read_at | null = unread |
| created_at | |

---

## 5. Authentication

### 5.1 Registration

- **Mobile:** 10–15 digits after stripping non-digits.
- **Password:** min 6 characters.
- **Full name:** required, 1–120 chars.

**API:** `POST /api/v1/auth/register`  
**Web:** `POST /auth/register` → redirect to login.

Duplicate mobile → **409** (API) or form error (web).

### 5.2 Login

**API:** `POST /api/v1/auth/login` → `{ "access_token", "token_type": "bearer" }`  
**Web:** `POST /auth/login` → session cookie `user_id`.

JWT payload: `{ "sub": "<user_id>", "exp": ... }`  
Default expiry: **7 days** (`ACCESS_TOKEN_EXPIRE_MINUTES=10080`).

**API auth header:** `Authorization: Bearer <token>`

### 5.3 Logout

**Web only:** `POST /auth/logout` clears session.  
**Mobile:** discard token locally.

---

## 6. Screens & navigation

### 6.1 Screen map (recommended mobile)

```
Login ──► Register
  │
  └──► Organizations list
         ├──► New organization
         └──► Organization detail
                ├── Section: Finances (#finances)
                ├── Section: Members (#members)
                ├── Section: Events (#events)
                └── Section: Activity (#activity)
                       └──► Event detail
                              ├── This event / balances (#balances)
                              ├── Members (#members)
                              ├── Expenses (#expenses)
                              ├── Activity (#activity)
                              └── Expense edit (full page on web)
Notifications (global) ──► /notifications
```

**Android (existing):** `login` → `register` → `orgs` → `org/{id}` → `event/{id}` (Compose). Does not yet implement all web Finances UI or notifications API.

### 6.2 Organizations list (`/orgs`)

**Purpose:** Home after login.

**Shows:**
- Hero + “New organization” button.
- **Personal totals card** (all orgs combined):
  - Shared purse (`total_manual_contributed`)
  - Bill credits (`total_expense_pool_credited`)
  - Your share (`total_expended`)
  - You have left (`total_remaining`)
- Grid of org cards: name, event count, created date.

**Actions:** Tap org → org detail; create org → form.

**API:** `GET /me`, `GET /organizations`, `POST /organizations`.

### 6.3 New organization (`/orgs/new`)

**Fields:** Name (required, max 200).

**On create:** Creator becomes org member and `created_by_user_id`. Activity `org_created` for creator.

### 6.4 Organization detail (`/orgs/{id}`)

**Header:** Org name, edit name (creator only), delete org (creator only).

**Sticky nav:** Finances | Members | Events | Activity

#### 6.4.1 Finances (`#finances`)

**Summary (current web UI):** Single box — **Total expenditure** only (all events in org).

**Left column:**
- **Add to shared purse** form:
  - Member (dropdown of org roster)
  - Amount ₹ (min 0.01)
  - Note (optional, max 200)
  - Submit → manual contribution
- **Ledgers** (tabs):
  - **Shared purse:** manual entries table (When, Person, Amount, Note, Edit/Delete if allowed)
  - **Bill-front:** expense-linked credits (read-only actions; edit via expense). Link to event if `event_id` present.

**Right column — Per person table** (`#balances` anchor):

| Column | Source field |
|--------|----------------|
| Member | name |
| Shared purse | `manual_contributed` |
| Paid on bills | `expense_front_pool` |
| Your share | `expended` |
| Settlement | `remaining` (green if ≥ 0, red if < 0) |

Footer hint: `Settlement = shared purse + paid on bills − your share`

**API used:** `GET /organizations/{id}`, `GET /organizations/{id}/balances`, `GET /organizations/{id}/contributions`, `POST/PATCH/DELETE .../contributions`.

#### 6.4.2 Members (`#members`)

- List: full name, mobile, Remove/Leave button when allowed.
- **Invite by mobile:** must already be registered.

**Remove rules:**
- **Self-leave:** allowed unless you are org creator (must delete org instead).
- **Remove other:** only if you invited them (`created_by_user_id`); cannot remove org creator.

#### 6.4.3 Events (`#events`)

- List events with Open, rename (creator), delete (creator).
- **New event** form: name → creates event + adds creator as member.

#### 6.4.4 Activity (`#activity`)

- Collapsible recent activity for this org (recipient = current user).
- Unread rows highlighted; link to event when `event_id` set.

### 6.5 Event detail (`/events/{id}`)

**Header:** Event name, org name breadcrumb, manage menu (rename/delete if creator).

**Nav:** This event | Org finances (link to `/orgs/{id}#finances`) | Members | Expenses | Activity

#### 6.5.1 This event / Balances (`#balances`)

**Summary:** Single box — **Total expenditure** for this event only.

**Per-person section** (expanded by default):
- Avatar + name
- **Share (this event):** `expended` from event balances
- If member has linked account **and** org roster row:
  - **Org-wide mini block:** Shared purse, Paid on bills, Your share, Settlement (from org balances)
- Else: message to link account or join org roster

**Help modal:** Explains event vs org finances and bill-front vs purse.

#### 6.5.2 Members (`#members`)

- Rows: avatar, name, mobile or “No account linked”
- **Add member** modal:
  1. **From organization:** search by name/mobile → suggestions API → pick user (`from_org_user_id`) or manual add
  2. **Manual:** display name and/or registered mobile
- **Edit/Delete** (if `can_manage`): inline collapse; delete blocked if member has splits

#### 6.5.3 Expenses (`#expenses`)

- **Excel report** download
- **Add expense** modal (if members exist)
- Accordion list: date, title, category, total; expand for split lines
- Edit/Delete expense (if creator/manage allowed)

#### 6.5.4 Add / Edit expense

**Fields:**
- Title, category (datalist: Food, Transport, Lodging, Activities, Supplies, Other)
- Total ₹, date
- **Who fronted this bill?** Radio: default = person saving; or radio on each split row (members with linked account only)
- **Split lines:** member, amount **or** percent (not both per line)
- **Split equally:** divide total across all event members; remainder paise assigned to largest share line
- Splits must sum to total exactly (server adjusts ≤ ₹0.02 to largest line)

**Web:** `splits_json` hidden field with JSON array of `{ member_id, amount?, percent? }`.

**On save:** Creates expense + splits + bill-front org contribution.

#### 6.5.5 Activity

Same pattern as org activity, scoped to event.

### 6.6 Notifications (`/notifications`)

- Grouped by organization → event
- Mark one read / mark all read
- Navbar badge: unread count (middleware)

**API:** `GET /me/activities`, `GET /me/activities/grouped`, `POST /me/activities/{id}/read`, `POST /me/activities/read-all`.

### 6.7 Auth screens

- **Login:** mobile, password
- **Register:** mobile, password, full name → success → login

---

## 7. User flows (step-by-step)

### 7.1 Onboarding

1. Register with mobile/password/name.
2. Sign in.
3. Create organization OR get invited by mobile to existing org.

### 7.2 Invite to organization

1. Org member opens Members section.
2. Enters invitee’s mobile (must be registered).
3. Invitee sees org on next login.

### 7.3 Create event & add people

1. Org detail → Events → create event (creator auto-added).
2. Event detail → Add member:
   - From org search, or
   - Manual name, or
   - Mobile linking to registered user.
3. At least one member required before expenses.

### 7.4 Record shared purse deposit

1. Org → Finances → Add to shared purse.
2. Pick org member, amount, optional note.
3. Appears in Shared purse ledger; increases that person’s `manual_contributed` and org `pool_available`.

### 7.5 Record expense

1. Event → Add expense.
2. Enter bill details and splits.
3. Optionally pick who fronted the bill (split-row radio).
4. Save → splits update event balances; bill-front credit updates org `expense_front_pool` for creditor; activity to linked event users.

### 7.6 Settlement review

1. Org → Finances → Per person table.
2. Each row: credits vs share → settlement column.
3. Event page: optional org-wide snapshot on linked member cards.

### 7.7 Export

1. Event → Excel report.
2. Downloads multi-sheet `.xlsx` (Summary, Expenses, Org pool, Split lines).

### 7.8 Leave / delete

- Leave org (non-creator): Members → Leave.
- Delete org (creator): deletes all events, members, expenses, activities.
- Delete event (creator): cascades members/expenses.
- Delete member: only if no splits; manager = who added them or event creator.

---

## 8. REST API reference

**Prefix:** `/api/v1`  
**Auth:** Bearer JWT except register/login.

### 8.1 Auth & profile

| Method | Path | Body / response |
|--------|------|-----------------|
| POST | `/auth/register` | `{ mobile, password, full_name }` → `{ id, mobile, full_name }` |
| POST | `/auth/login` | `{ mobile, password }` → `{ access_token, token_type }` |
| GET | `/me` | Profile + balance summary (see §3.2) |

### 8.2 Activities

| Method | Path | Notes |
|--------|------|-------|
| GET | `/me/activities` | Flat list, max 300 |
| GET | `/me/activities/grouped` | `{ organization_id, organization_name, event_groups: [{ event_id, event_name, activities: [...] }] }` |
| POST | `/me/activities/{id}/read` | `{ ok: true }` |
| POST | `/me/activities/read-all` | `{ ok, marked }` |
| GET | `/organizations/{org_id}/activities` | Org-scoped for current user |
| GET | `/events/{event_id}/activities` | Event-scoped |

**Activity object:** `{ id, organization_id?, event_id?, actor_user_id?, kind, summary, read_at?, created_at }`

### 8.3 Organizations

| Method | Path | Notes |
|--------|------|-------|
| GET | `/organizations` | List for current user |
| POST | `/organizations` | `{ name }` |
| GET | `/organizations/{id}` | Includes `pool_available`, `pool_total_contributed` (manual only), `pool_total_expenses` |
| PATCH | `/organizations/{id}` | `{ name }` — creator only |
| DELETE | `/organizations/{id}` | 204 — creator only |
| POST | `/organizations/{id}/members` | `{ mobile }` invite |
| DELETE | `/organizations/{id}/memberships/{membership_id}` | 204 |
| GET | `/organizations/{id}/balances` | `[MemberBalance]` org-wide |
| GET | `/organizations/{id}/contributions` | All contributions (manual + bill-front) |
| POST | `/organizations/{id}/contributions` | `{ user_id, amount, note? }` — manual only |
| PATCH | `/organizations/{id}/contributions/{cid}` | Manual only; not expense-linked |
| DELETE | `/organizations/{id}/contributions/{cid}` | Manual only |
| GET | `/organizations/{id}/events` | `[EventRead]` with `organization_pool_available` |
| POST | `/organizations/{id}/events` | `{ name }` |

### 8.4 Events

| Method | Path | Notes |
|--------|------|-------|
| GET | `/events/{id}` | `EventRead` + pool available |
| PATCH | `/events/{id}` | `{ name }` — event creator |
| DELETE | `/events/{id}` | 204 — event creator |
| GET | `/events/{id}/members` | `[MemberRead]` |
| POST | `/events/{id}/members` | `MemberCreate` |
| PATCH | `/events/{id}/members/{mid}` | `{ name?, mobile? }` |
| DELETE | `/events/{id}/members/{mid}` | 204 |
| GET | `/events/{id}/org-member-suggestions?q=` | Search org roster not yet on event |
| GET | `/events/{id}/expenses` | Newest first |
| POST | `/events/{id}/expenses` | `ExpenseCreate` |
| PATCH | `/events/{id}/expenses/{eid}` | Full replace via `ExpenseCreate` body |
| DELETE | `/events/{id}/expenses/{eid}` | 204 |
| GET | `/events/{id}/balances` | Event-level shares only |
| GET | `/events/{id}/export.xlsx` | Binary Excel |

### 8.5 Key request/response shapes

**MemberBalance:**
```json
{
  "member_id": 1,
  "user_id": 2,
  "name": "Alice",
  "contributed": "1500.00",
  "manual_contributed": "500.00",
  "expense_front_pool": "1000.00",
  "expended": "800.00",
  "remaining": "700.00"
}
```

**ExpenseCreate:**
```json
{
  "title": "Groceries",
  "category": "Food",
  "amount_total": "1200.00",
  "expense_date": "2026-03-15",
  "splits": [
    { "member_id": 1, "amount": "600.00" },
    { "member_id": 2, "percent": "50" }
  ],
  "pool_creditor_member_id": 2,
  "pool_credit_user_id": null
}
```

**OrgPoolContributionRead:** includes `expense_id`, `event_id` when bill-front.

### 8.6 HTTP errors

| Code | Typical cause |
|------|----------------|
| 400 | Validation (splits don’t sum, invalid mobile, member has splits on delete) |
| 401 | Invalid/missing JWT |
| 403 | Permission (not creator, can’t manage resource) |
| 404 | Org/event not found OR user not a member (API hides existence) |
| 409 | Duplicate mobile on register |

Error body (API): `{ "detail": "message" }` or validation array.

---

## 9. Permissions matrix

| Action | Who can do it |
|--------|----------------|
| Rename org | Org `created_by_user_id` |
| Delete org | Org creator |
| Invite org member | Any org member |
| Leave org | Any member except org creator |
| Remove org member | Inviter (`created_by_user_id`) OR self-leave; not creator |
| Create event | Any org member |
| Rename/delete event | Event `created_by_user_id` |
| Add event member | Any org member with event access |
| Edit/delete event member | Who added them OR event creator |
| Add manual purse entry | Any org member |
| Edit/delete manual purse entry | Who logged it (`created_by_user_id`) OR org creator fallback |
| Edit/delete bill-front entry | **Via expense only** (contribution endpoints reject) |
| Create expense | Any org member with event access |
| Edit/delete expense | Expense creator OR event creator if expense has no creator |
| Export Excel | Any org member with event access |

---

## 10. Activity / notification kinds

| kind | When emitted | Typical recipients |
|------|--------------|-------------------|
| `org_created` | Org created | Creator |
| `org_member_added` | User invited to org | New member (+ org?) |
| `event_created` | New event | All org members |
| `member_added` | Member added to event | Event linked users + new member |
| `contribution_added` | Manual purse deposit | All org members |
| `expense_added` | New expense | Event linked users; per-user summary includes **their split share** |

Expense activity for linked users: `"Alice added expense \"Groceries\" (your share ₹300.00) in \"Trip\""`.

---

## 11. Expense split algorithm

1. Each split line: **either** `amount` **or** `percent`, not both.
2. Percent lines: `amount = total × percent / 100`, rounded to 2 decimals.
3. Sum all split amounts; if off by ≤ ₹0.02, adjust **largest** split line.
4. If off by more → error.
5. Duplicate `member_id` on multiple lines: amounts **add** for that member.

**Equal split (client-side, web/Android):**
- Divide `total` by member count.
- Distribute base paise; give extra ₹0.01 to first N members so sum equals total exactly.

**Web UX extras:**
- Adding/removing split row re-runs equal split when total is valid.
- Pool creditor radio on split row: disabled if member has no `user_id`.

---

## 12. Excel export structure

**Endpoint:** `GET /events/{event_id}/export.xlsx`

**Sheets:**
1. **Summary** — org name, event name, generated time, shared purse unspent, per-member: this event share + org columns (shared purse, paid on bills, org share, settlement).
2. **Expenses** — date, item, category, total, split summary text.
3. **Org pool** — manual purse entries only (When, Person, Amount, Note).
4. **Split lines** — flat list of every split row.

**Filename pattern:** `expense_report_{event_slug}_{event_id}_{YYYYMMDD}.xlsx`

---

## 13. Web vs mobile parity notes

### 13.1 Existing Android app (`android/`)

**Implemented:** Login, register, org list/create, org detail (partial), event detail tabs (members, pool, expenses, balances), equal/custom splits, Excel download.

**API client gaps vs current backend:**
- `UserMe` missing `total_manual_contributed`, `total_expense_pool_credited`.
- `MemberBalanceRead` missing `manual_contributed`, `expense_front_pool`.
- `OrgPoolContributionRead` missing `expense_id`, `event_id`, `created_by_user_id`.
- No activities/notifications API calls.
- No PATCH/DELETE for org/event/member/expense/contribution.
- No `pool_creditor_member_id` on expense unless added to UI.
- Org detail may still reflect older “pool” UX — align with **Finances** section (§6.4.1).

### 13.2 Recommended mobile UI (match current web)

| Screen | Primary metrics to show |
|--------|-------------------------|
| Org list | Personal totals (4 metrics from `/me`) |
| Org Finances | **Total expenditure** hero + per-person table + deposit form + ledger tabs |
| Event | **Total expenditure** hero + per-person event share + optional org settlement block |
| Event | No org-wide purse summary card (removed from web) |

### 13.3 Money display

- Format as ₹ with 2 decimals (e.g. `₹1,234.56` or `₹1234.56`).
- Use decimal type in mobile (BigDecimal / Decimal), not float, for money math.
- API returns numbers as JSON floats in `/me` but decimals as strings in Pydantic models for balances/expenses.

---

## 14. Validation & edge cases

| Scenario | Behavior |
|----------|----------|
| Expense with no splits | Rejected |
| Split member not on event | 400 |
| Split member not in expense create payload member list | 400 for pool creditor pick |
| Delete member with splits | Error: remove splits first |
| Invite duplicate org member | Error |
| Add same user twice to event | Error |
| Link mobile to member already on event | Error |
| Org creator tries to leave | Error: delete org instead |
| Edit bill-front contribution directly | 403 — edit expense |
| Delete expense | Cascades splits + expense-linked contribution |
| Event member without `user_id` | Counts in event splits; **not** in org `expended` until linked |
| Name-only event member | Can appear on splits; no org settlement row |
| `pool_available` negative | Allowed (overspent vs manual purse) |
| JWT expired | 401 — re-login |

---

## 15. Environment & deployment

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` / `SESSION_SECRET` | Web sessions |
| `JWT_SECRET` | API tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default 10080 (7 days) |
| `DATABASE_URL` | Postgres (required on Vercel) |

**Local run:**
```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**OpenAPI docs:** `http://host:8000/docs`

---

## 16. Suggested mobile screen checklist

Use this when implementing screens:

- [ ] **Auth:** Login, Register, token storage, 401 → login
- [ ] **Orgs list:** `/me` summary + org cards
- [ ] **Org create**
- [ ] **Org detail — Finances:** total expenditure, per-person table, add deposit, ledger tabs (filter manual vs bill-front client-side using `expense_id`)
- [ ] **Org detail — Members:** list, invite, leave/remove
- [ ] **Org detail — Events:** list, create, open
- [ ] **Org detail — Activity:** list + deep link to event
- [ ] **Event detail — Summary:** total expenditure only
- [ ] **Event detail — Per person:** event share + org settlement if linked
- [ ] **Event detail — Members:** list, add (suggestions API), edit, delete
- [ ] **Event detail — Expenses:** list, add modal, edit, delete, bill-front picker
- [ ] **Event detail — Export:** download/share xlsx
- [ ] **Notifications:** grouped feed, read/unread, badge count
- [ ] **Permissions:** hide edit/delete when API would 403; creator-only actions

---

## 17. Glossary

| Term | Meaning |
|------|---------|
| **Shared purse** | Manual org deposits (`expense_id` null) |
| **Bill-front / Paid on bills** | Expense-linked credit to whoever paid the full bill |
| **Your share / Contri** | Sum of expense split amounts attributed to a person |
| **Settlement / Remaining** | Total credits minus share |
| **Total expenditure** | Sum of expense bill totals (not splits) |
| **Event member** | Person on splits for one event |
| **Org member** | Registered user on organization roster |

---

*Document generated from codebase state: FastAPI v2.0, org Finances UI with single total expenditure hero, event page without org-wide money card. Update this file when backend or web UX changes.*
