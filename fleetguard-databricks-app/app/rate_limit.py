"""Rate limiting for the chat endpoints (spec section 10).

slowapi keys on the client address by default, which is the right unit here:
the concern is one runaway browser tab or a demo left open, not a distributed
attack. The limit is configuration, not a constant, because a live demo and a
CI run want different numbers.

Kept in its own module so the limiter instance can be imported by both the
router that decorates with it and the app factory that registers its state,
without either importing the other.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[])


def rate_limit_response(request, exc):
    """Same error envelope as everything else, plus how long to wait."""
    from fastapi.responses import JSONResponse

    from app.logging_config import request_id_var

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "message": (
                f"Too many assistant requests. The limit is "
                f"{settings.CHAT_RATE_LIMIT}. Wait a moment and try again."
            ),
            "request_id": request_id_var.get(),
        },
    )
