from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging

from routers.auth import router as auth_router, seed_admin
from routers.meetings import router as meetings_router
from routers.recording import router as recording_router
from routers.processing import router as processing_router
from routers.review import router as review_router
from routers.admin import router as admin_router
from utils.storage import init_storage
from utils.seed import seed_standards, migrate_standard_outcomes, migrate_cqc_key_questions, migrate_analyses_key_questions
from fastapi import APIRouter

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

    await seed_admin(db)
    await seed_standards(db)
    await migrate_standard_outcomes(db)
    await migrate_cqc_key_questions(db)
    await migrate_analyses_key_questions(db)

    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown():
    client.close()
