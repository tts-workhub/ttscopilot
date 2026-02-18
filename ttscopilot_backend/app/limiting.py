from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def limiter_key(request: Request) -> str:
    # Prefer per-user if available, else fallback to IP
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return get_remote_address(request)

limiter = Limiter(key_func=limiter_key)
