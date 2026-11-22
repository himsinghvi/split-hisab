"""Runs after SessionMiddleware so `request.session` is available."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class UnreadNotificationsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.activity_service import count_unread
        from app.database import SessionLocal
        from app.models import User

        request.state.unread_notifications = 0
        request.state.current_user_name = None
        request.state.current_user_mobile = None
        try:
            uid = request.session.get("user_id")
        except (AssertionError, AttributeError):
            uid = None
        if uid:
            db = SessionLocal()
            try:
                request.state.unread_notifications = count_unread(db, int(uid))
                u = db.get(User, int(uid))
                if u:
                    request.state.current_user_name = (u.full_name or "").strip() or u.mobile
                    request.state.current_user_mobile = u.mobile
            finally:
                db.close()
        return await call_next(request)
