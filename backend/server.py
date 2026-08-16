from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, APIRouter, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
import asyncio  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402

import database  # noqa: E402
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
if _loki_url and _loki_user and _loki_token:
    attach_loki(_loki_url, _loki_user, _loki_token)
    logger.info("Loki log shipping enabled → %s", _loki_url)
else:
    logger.warning("Loki credentials not set — logging to console only")

app = FastAPI(title="Supervision 2.0 API")

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

app.add_middleware(SecurityHeadersMiddleware)

cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

# H3: Restrict CORS to the specific methods and headers the API actually uses.
# Wildcards increase the attack surface unnecessarily. Guard against accidental
# misconfiguration that sets CORS_ORIGINS to "*" (would allow any origin with credentials).
if "*" in cors_origins:
    logger.critical(
        "SECURITY: CORS_ORIGINS contains '*' — this is unsafe with allow_credentials=True. "
        "Set an explicit allowlist of trusted origins."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

api_router = APIRouter(prefix="/api")
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

    pool = await database.create_pool()
    app.state.pool = pool
    logger.info("PostgreSQL pool ready")

    # Warm the in-process standards cache (system standards never change)
    from utils.standards_cache import warm as warm_standards
    async with database.with_admin() as conn:
        await warm_standards(conn)

    # Run schema creation/migration on every startup (all statements are idempotent)
    await create_schema()
    logger.info("Schema verified")

    await seed_all()
    logger.info("Seeding complete")

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
