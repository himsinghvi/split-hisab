from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse


def session_user_id(request: Request) -> int | None:
    v = request.session.get("user_id")
    return int(v) if v is not None else None


def require_session_user(request: Request) -> int | RedirectResponse:
    uid = session_user_id(request)
    if uid is None:
        return RedirectResponse("/auth/login", status_code=302)
    return uid


def require_session_user_json(request: Request) -> int:
    """For web endpoints that return JSON (fetch/XHR). Never redirect to HTML login."""
    uid = session_user_id(request)
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in. Please refresh and sign in again.",
        )
    return uid
