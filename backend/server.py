from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, APIRouter, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
import asyncio  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402

import database  # noqa: E402
from routers.dashboard import router as dashboard_router  # noqa: E402
from routers.auth import router as auth_router  # noqa: E402
from routers.meetings import router as meetings_router  # noqa: E402
from routers.recording import router as recording_router  # noqa: E402
from routers.processing import router as processing_router  # noqa: E402
from routers.review import router as review_router  # noqa: E402
from routers.admin import router as admin_router  # noqa: E402
from routers.portfolio import router as portfolio_router  # noqa: E402
from routers.org import router as org_router  # noqa: E402
from routers.super_admin import router as super_admin_router  # noqa: E402
from routers.schedules import router as schedules_router  # noqa: E402
from routers.doc_uploads import router as doc_uploads_router  # noqa: E402
from routers.prep import router as prep_router  # noqa: E402
from routers.resources import router as resources_router  # noqa: E402
from routers.eula import router as eula_router  # noqa: E402
from utils.storage import init_storage  # noqa: E402
from utils.seed import seed_all  # noqa: E402
from utils.job_worker import start_worker  # noqa: E402
from init_db import create_schema  # noqa: E402
from loki_logging import attach_loki  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Attach Loki handler if credentials are present
_loki_url = os.environ.get("LOKI_URL", "")
_loki_user = os.environ.get("LOKI_USER", "")
_loki_token = os.environ.get("LOKI_TOKEN", "")
_app_env = os.environ.get("APP_ENV", "production")
if _loki_url and _loki_user and _loki_token:
    attach_loki(_loki_url, _loki_user, _loki_token, env=_app_env)
    logger.info("Loki log shipping enabled → %s (env=%s)", _loki_url, _app_env)
else:
    logger.warning("Loki credentials not set — logging to console only")

from starlette.middleware.gzip import GZipMiddleware

app = FastAPI(title="Supervision 2.0 API")

# A malformed id in a path/query param (e.g. GET /api/meetings/not-a-uuid) now
# hits Postgres's uuid parser directly since id columns are native UUID
# (Phase 2 migration) — map that to a clean 404 instead of a 500.
from fastapi.responses import JSONResponse  # noqa: E402
from asyncpg.exceptions import InvalidTextRepresentationError  # noqa: E402


@app.exception_handler(InvalidTextRepresentationError)
async def _invalid_uuid_handler(request: Request, exc: InvalidTextRepresentationError):
    return JSONResponse(status_code=404, content={"detail": "Not found"})

# ── Path-aware request body size limits ───────────────────────────────────────
# Checked via Content-Length header BEFORE the body is read — zero memory cost.
# Handlers that read files already apply their own in-memory guards, but this
# middleware catches oversized requests at the HTTP layer for all endpoints.
_ROUTE_SIZE_LIMITS = [
    ("/api/processing/", 360 * 1024 * 1024),        # audio upload — 360 MB
    ("/api/doc-uploads/", 26 * 1024 * 1024),         # supervision doc — 26 MB
    ("/api/admin/standards/upload", 30 * 1024 * 1024),  # standards doc — 30 MB
    ("/api/org/branding/logo", 3 * 1024 * 1024),     # org logo — 3 MB
]
_DEFAULT_BODY_LIMIT = 1 * 1024 * 1024  # 1 MB for all JSON endpoints


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length header exceeds the route limit."""

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                size = int(cl)
            except ValueError:
                size = 0
            limit = _DEFAULT_BODY_LIMIT
            for prefix, max_bytes in _ROUTE_SIZE_LIMITS:
                if request.url.path.startswith(prefix):
                    limit = max_bytes
                    break
            if size > limit:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": "Request body too large"},
                    status_code=413,
                )
        return await call_next(request)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # CSP built once at class level — same value for every response
    _CSP = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://orsxhtlpybxoexdjrbnx.supabase.co; "
        "connect-src 'self' https:; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = self._CSP
        return response

app.add_middleware(GZipMiddleware, minimum_size=500)  # compress JSON ≥ 500 bytes
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ContentSizeLimitMiddleware)

cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# H3: Restrict CORS to the specific methods and headers the API actually uses.
# Wildcards increase the attack surface unnecessarily. Hard-fail on startup rather
# than just warning — a misconfigured "*"/empty allowlist with allow_credentials=True
# is a critical security bug, not something that should silently keep running.
if not cors_origins or "*" in cors_origins:
    raise RuntimeError(
        "SECURITY: CORS_ORIGINS must be set to an explicit, non-empty allowlist of "
        "trusted origins (comma-separated) — refusing to start with '*' or empty."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

api_router = APIRouter(prefix="/api")
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(meetings_router, prefix="/meetings", tags=["meetings"])
api_router.include_router(recording_router, prefix="/recording", tags=["recording"])
api_router.include_router(processing_router, prefix="/processing", tags=["processing"])
api_router.include_router(review_router, prefix="/review", tags=["review"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
api_router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(org_router, prefix="/org", tags=["org"])
api_router.include_router(super_admin_router, prefix="/super-admin", tags=["super-admin"])
api_router.include_router(schedules_router, prefix="/schedules", tags=["schedules"])
api_router.include_router(doc_uploads_router, prefix="/doc-uploads", tags=["doc-uploads"])
api_router.include_router(prep_router, tags=["prep"])
api_router.include_router(resources_router, prefix="/resources", tags=["resources"])
api_router.include_router(eula_router, prefix="/eula", tags=["eula"])
app.include_router(api_router)




@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Supervision 2.0"}


_KNOWN_WEAK_SECRETS = {
    "secret", "your-secret", "changeme", "jwt_secret", "mysecret",
    "dev_secret", "supersecret", "jwttoken", "example", "test",
}


def _validate_startup_secrets():
    """SEC-005: Fail fast or warn loudly on weak/missing secrets."""
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if not jwt_secret:
        raise RuntimeError(
            "CRITICAL SECURITY: JWT_SECRET is not set. "
            "Generate a strong secret (e.g. openssl rand -hex 32) and set it "
            "in the JWT_SECRET environment variable before starting."
        )
    if len(jwt_secret) < 32 or jwt_secret.lower() in _KNOWN_WEAK_SECRETS:
        logger.critical(
            "SECURITY WARNING: JWT_SECRET is weak (less than 32 characters or a known default). "
            "Rotate it immediately: generate a new value with `openssl rand -hex 32` "
            "and update JWT_SECRET in your production .env file."
        )


@app.on_event("startup")
async def startup():
    _validate_startup_secrets()

    # Run schema creation/migration BEFORE the pool is created — m011 creates
    # the app_default role that the pool's DSN authenticates as, so on a
    # fresh database that role doesn't exist yet until this runs.
    await create_schema()
    logger.info("Schema verified")

    pool = await database.create_pool()
    app.state.pool = pool
    logger.info("PostgreSQL pool ready")

    # Warm the in-process standards cache AFTER seeding so the cache always
    # reflects the current DB state (including any rows seeded this boot).
    # Previously this ran before seed_all() which left the cache stale if
    # new system standards were inserted on first boot after a fix.
    from utils.standards_cache import warm as warm_standards

    try:
        await seed_all()
        logger.info("Seeding complete")
    except Exception:
        # Never let a seeding hiccup (transient DB error, bad env value, etc.)
        # take the whole API offline — that blocks ALL logins, not just seeding.
        logger.exception("seed_all() failed — continuing startup without it")

    async with database.with_admin() as conn:
        await warm_standards(conn)

    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

    asyncio.create_task(start_worker())
    logger.info("Job queue worker started")


@app.on_event("shutdown")
async def shutdown():
    await database.close_pool()
