from .qrsession import SessionQR


def generate_session_token(request_id: str, session: SessionQR) -> str:
    """Generate a one-time token for this session."""
    key = f"session:{session.id}"
    now = timezone.now()
    payload = {
        "session_id": str(session.id),
        "created_at": now.isoformat(),
        "expires_at": session.expires_at.isoformat(),
    }
    token = jwt.encode(payload, str(session.session_key), algorithm="HS256")
    cache.set(key, "1", timeout=settings.SESSION_TOKEN_TIMEOUT)
    return token
