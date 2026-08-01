from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, APIRouter  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import asyncio  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402

from routers.auth import router as auth_router, seed_admin  # noqa: E402
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
from utils.seed import seed_standards, migrate_standard_outcomes, migrate_cqc_key_questions, migrate_analyses_key_questions, seed_super_admin, seed_default_org, seed_quality_statements_migration, migrate_standards_entries_system_flag  # noqa: E402,E501
from utils.job_worker import start_worker  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Supervision 2.0 API")

cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.on_event("startup")
async def startup():
    app.state.db = db
    await db.users.create_index("email", unique=True)
    await db.meetings.create_index([("created_by", 1), ("created_at", -1)])
    await db.standards_entries.create_index([("type", 1), ("reference", 1)])
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    # Job queue indexes — status+created_at for fast FIFO polling
    await db.jobs.create_index([("status", 1), ("attempts", 1), ("created_at", 1)])

    await seed_admin(db)
    await seed_super_admin(db)
    await seed_standards(db)
    await seed_quality_statements_migration(db)
    await migrate_standard_outcomes(db)
    await migrate_cqc_key_questions(db)
    await migrate_analyses_key_questions(db)
    await migrate_standards_entries_system_flag(db)
    await seed_default_org(db)

    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

    # Start persistent job queue worker
    asyncio.create_task(start_worker(db))
    logger.info("Job queue worker started")


@app.on_event("shutdown")
async def shutdown():
    client.close()
