import logging
import os
import time

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
import redis.asyncio
import redis.exceptions
from sqlalchemy import text

from app.db.session import SessionLocal

from app.api.router import api_router
from app.core.config import get_settings

settings = get_settings()

# --- Issue 4: SECRET_KEY Validation ---
if settings.app_env != "development" and settings.secret_key == "change-me-super-secret":
    raise RuntimeError(
        "FATAL: SECRET_KEY is set to the default value. "
        "Set a strong, unique SECRET_KEY before running in production."
    )

os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
logger.remove()
logger.add(
    settings.log_file,
    level=settings.log_level.upper(),
    rotation="10 MB",
    retention="10 days",
    enqueue=True,
)
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

app = FastAPI(
    title="БАЗА API",
    description="API платформы БАЗА для B2B-лидогенерации",
    version="1.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    openapi_url="/openapi.json" if settings.app_env == "development" else None,
)

# --- Rate Limiting Middleware (disabled in development) ---
_rate_limit_redis = redis.asyncio.Redis.from_url(settings.redis_url, decode_responses=True)

# Rate limit tiers: path prefix -> (max_requests, window_seconds)
# In development, use very generous limits to avoid blocking during dev/testing
_is_dev = settings.app_env == "development"
_RATE_LIMIT_TIERS: list[tuple[str, int, int]] = [
    ("/api/auth/login", 100 if _is_dev else 10, 60),
    ("/api/auth/register", 100 if _is_dev else 10, 60),
    ("/api/auth/forgot-password", 100 if _is_dev else 10, 60),
    ("/api/auth/reset-password", 100 if _is_dev else 10, 60),
    ("/api/auth/", 500 if _is_dev else 60, 60),
    ("/api/", 1000 if _is_dev else 120, 60),
]


def _get_rate_limit(path: str) -> tuple[int, int] | None:
    for prefix, max_req, window in _RATE_LIMIT_TIERS:
        if path.startswith(prefix):
            return max_req, window
    return None


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    limit = _get_rate_limit(path)
    if limit is None:
        return await call_next(request)

    max_requests, window = limit
    client_ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")
    # Use the matched prefix for the key so all sub-paths in a tier share the bucket
    matched_prefix = path
    for prefix, mr, w in _RATE_LIMIT_TIERS:
        if path.startswith(prefix) and mr == max_requests and w == window:
            matched_prefix = prefix
            break
    key = f"rate_limit:{client_ip}:{matched_prefix}:{int(time.time()) // window}"
    try:
        pipe = _rate_limit_redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        results = await pipe.execute()
        current = results[0]
        if current > max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Слишком много запросов. Попробуйте позже."},
                headers={"Retry-After": str(window)},
            )
    except redis.exceptions.RedisError:
        # If Redis is down, allow the request through rather than blocking all traffic
        logger.warning("Rate limiter Redis unavailable, allowing request through")

    return await call_next(request)

_cors_kwargs: dict = dict(
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Org-Id"],
)
if settings.app_env == "development":
    _cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(CORSMiddleware, **_cors_kwargs)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


@app.middleware("http")
async def request_logger(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({elapsed_ms:.1f}ms)")
        return response
    except Exception:
        logger.exception(f"Unhandled error at {request.method} {request.url.path}")
        raise


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    await _rate_limit_redis.ping()
    return {"status": "ready"}


# API Versioning Strategy:
# All routes are served under /api/ prefix (defined in app.api.router).
# This is treated as API v1. When a v2 is needed, create a separate
# api_v2_router with prefix="/api/v2" and mount it alongside the existing
# router. The current /api/ prefix can be aliased to /api/v1/ at that point.
app.include_router(api_router)
