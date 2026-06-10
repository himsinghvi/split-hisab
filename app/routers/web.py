import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import activity_service, excel_export, services
from app.auth_web import require_session_user, session_user_id
from app.database import get_db
from app.schemas import ExpenseCreate, ExpenseSplitInput

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _money(d: Decimal | float) -> str:
    return f"₹{Decimal(str(d)):.2f}"


templates.env.filters["money"] = _money


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if session_user_id(request):
        return RedirectResponse("/orgs", status_code=status.HTTP_302_FOUND)
    return RedirectResponse("/auth/login", status_code=status.HTTP_302_FOUND)


@router.get("/orgs", response_class=HTMLResponse)
def page_orgs(request: Request, db: Session = Depends(get_db)):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    orgs = services.list_organizations_for_user(db, uid)
    summary = services.user_personal_balance_summary(db, uid)
    return templates.TemplateResponse(
        request,
        "orgs.html",
        {
            "orgs": orgs,
            "title": "Your organizations",
            "summary": summary,
        },
    )


@router.get("/orgs/new", response_class=HTMLResponse)
def page_new_org(request: Request):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    return templates.TemplateResponse(
        request, "org_new.html", {"title": "New organization"}
    )


@router.post("/orgs/new")
def post_new_org(
    request: Request, name: str = Form(...), db: Session = Depends(get_db)
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    org = services.create_organization(db, uid, name)
    return RedirectResponse(
        f"/orgs/{org.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/orgs/{org_id}", response_class=HTMLResponse)
def page_org_detail(
    request: Request, org_id: int, db: Session = Depends(get_db)
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    org = services.get_organization(db, org_id)
    if not org or not services.user_in_organization(db, uid, org_id):
        raise HTTPException(404, "Organization not found")
    events = services.list_events_for_organization(db, org_id)
    org_activities = activity_service.list_for_org(db, uid, org_id, limit=40)
    return templates.TemplateResponse(
        request,
        "org_detail.html",
        {
            "org": org,
            "events": events,
            "title": org.name,
            "org_activities": org_activities,
        },
    )


@router.post("/orgs/{org_id}/members")
def post_org_add_member(
    request: Request,
    org_id: int,
    mobile: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    if not services.user_in_organization(db, uid, org_id):
        raise HTTPException(404, "Organization not found")
    try:
        services.add_organization_member_by_mobile(db, org_id, mobile, uid)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return RedirectResponse(
        f"/orgs/{org_id}#members", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/orgs/{org_id}/events/new")
def post_new_event(
    request: Request,
    org_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Event name is required")
    try:
        ev = services.create_event(db, org_id, uid, name)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return RedirectResponse(
        f"/events/{ev.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/events/{event_id}", response_class=HTMLResponse)
def page_event_detail(
    request: Request, event_id: int, db: Session = Depends(get_db)
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    if not services.user_can_access_event(db, uid, event_id):
        raise HTTPException(404, "Event not found")
    ev = services.get_event(db, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    balances = services.member_balances(db, event_id)
    expenses = sorted(
        ev.expenses, key=lambda e: (e.expense_date, e.id), reverse=True
    )
    contrib_rows = []
    for m in ev.members:
        for c in sorted(m.contributions, key=lambda x: x.created_at, reverse=True):
            contrib_rows.append(
                {
                    "id": c.id,
                    "member_name": m.name,
                    "amount": c.amount,
                    "note": c.note,
                    "created_at": c.created_at,
                }
            )
    contrib_rows.sort(key=lambda r: r["created_at"], reverse=True)

    mems = sorted(ev.members, key=lambda m: m.id)
    members_opts = [{"id": m.id, "name": m.name} for m in mems]

    balance_totals = {
        "pooled": Decimal("0"),
        "expended": Decimal("0"),
        "remaining": Decimal("0"),
    }
    for b in balances:
        balance_totals["pooled"] += b.contributed
        balance_totals["expended"] += b.expended
        balance_totals["remaining"] += b.remaining

    event_activities = activity_service.list_for_event(db, uid, event_id, limit=40)

    return templates.TemplateResponse(
        request,
        "event_detail.html",
        {
            "event": ev,
            "organization": ev.organization,
            "members": mems,
            "members_opts": members_opts,
            "balances": balances,
            "balance_totals": balance_totals,
            "expenses": expenses,
            "contributions": contrib_rows,
            "title": ev.name,
            "event_activities": event_activities,
        },
    )


@router.post("/events/{event_id}/members")
def post_add_event_member(
    request: Request,
    event_id: int,
    name: str = Form(""),
    mobile: str | None = Form(None),
    db: Session = Depends(get_db),
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    try:
        services.add_member(db, event_id, name, uid, mobile)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return RedirectResponse(
        f"/events/{event_id}#members", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/events/{event_id}/contributions")
def post_contribution(
    request: Request,
    event_id: int,
    member_id: int = Form(...),
    amount: Decimal = Form(...),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    if not services.user_can_access_event(db, uid, event_id):
        raise HTTPException(404, "Event not found")
    ev = services.get_event(db, event_id)
    if not ev or not any(m.id == member_id for m in ev.members):
        raise HTTPException(400, "Invalid member")
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    services.add_contribution(
        db,
        member_id,
        amount,
        (note or "").strip() or None,
        actor_user_id=uid,
    )
    return RedirectResponse(
        f"/events/{event_id}#pool", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/events/{event_id}/expenses")
def post_expense(
    request: Request,
    event_id: int,
    title: str = Form(...),
    category: str = Form(...),
    amount_total: Decimal = Form(...),
    expense_date: date = Form(...),
    splits_json: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    if not services.user_can_access_event(db, uid, event_id):
        raise HTTPException(404, "Event not found")
    ev = services.get_event(db, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    try:
        raw = json.loads(splits_json)
        if not isinstance(raw, list):
            raise ValueError("Invalid splits payload")
        splits = [ExpenseSplitInput(**row) for row in raw]
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid splits: {e}") from e

    mids = {m.id for m in ev.members}
    for s in splits:
        if s.member_id not in mids:
            raise HTTPException(400, "Split references unknown member")

    payload = ExpenseCreate(
        title=title.strip(),
        category=category.strip(),
        amount_total=amount_total,
        expense_date=expense_date,
        splits=splits,
    )
    try:
        services.create_expense(db, event_id, payload, actor_user_id=uid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    return RedirectResponse(
        f"/events/{event_id}#expenses", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/notifications", response_class=HTMLResponse)
def page_notifications(request: Request, db: Session = Depends(get_db)):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    rows = activity_service.list_for_user(db, uid, limit=400)
    grouped = activity_service.group_activities_hierarchy(db, rows)
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {
            "title": "Notifications",
            "grouped": grouped,
            "activities": rows,
        },
    )


@router.post("/notifications/read-all")
def post_notifications_read_all(request: Request, db: Session = Depends(get_db)):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    activity_service.mark_all_read(db, uid)
    return RedirectResponse("/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/notifications/{activity_id}/read")
def post_notification_read(
    request: Request, activity_id: int, db: Session = Depends(get_db)
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    activity_service.mark_read(db, uid, activity_id)
    return RedirectResponse("/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/events/{event_id}/export.xlsx")
def download_event_excel(
    request: Request, event_id: int, db: Session = Depends(get_db)
):
    uid = require_session_user(request)
    if isinstance(uid, RedirectResponse):
        return uid
    if not services.user_can_access_event(db, uid, event_id):
        raise HTTPException(404, "Event not found")
    out = excel_export.build_event_report_xlsx(db, event_id)
    if not out:
        raise HTTPException(404, "Event not found")
    content, filename = out
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
