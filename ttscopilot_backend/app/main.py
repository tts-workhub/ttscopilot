from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from .routers import users, personas
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Env validation EARLY ----
required = ["DATABASE_URL", "SECRET_KEY", "OPENAI_API_KEY"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

app = FastAPI(title="TTS Copilot Backend")

# ---- Rate limiting ----
from .limiting import limiter
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )

# ---- Routers ----
app.include_router(users.router)
app.include_router(personas.router)

@app.on_event("startup")
async def startup():
    logger.info("TTS Copilot Backend started")
    os.makedirs("screenshots", exist_ok=True)
