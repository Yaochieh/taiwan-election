from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.queries import init_db
from api.routers import elections, candidates, parties

app = FastAPI(
    title="正至 API",
    description="台灣選舉資訊平台 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(elections.router, prefix="/elections", tags=["elections"])
app.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
app.include_router(parties.router, prefix="/parties", tags=["parties"])


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
