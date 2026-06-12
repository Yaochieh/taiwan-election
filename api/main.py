from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from db.queries import init_db
from api.routers import elections, candidates, parties, platforms, trends, mayoral


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="正至 API",
    description="台灣選舉資訊平台 API — 選舉、候選人、政見、趨勢、地方首長歷屆結果",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://taiwan-election-web.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    # 允許 Vercel 的 preview deployments（每個 PR 都會有獨立網址）
    allow_origin_regex=r"https://taiwan-election-web-.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(elections.router, prefix="/elections", tags=["elections"])
app.include_router(candidates.router, prefix="/candidates", tags=["candidates"])
app.include_router(parties.router, prefix="/parties", tags=["parties"])
app.include_router(platforms.router, prefix="/platforms", tags=["platforms"])
app.include_router(trends.router, prefix="/trends", tags=["trends"])
app.include_router(mayoral.router, prefix="/mayoral", tags=["mayoral"])

# 公報圖檔以靜態資源開放（給前端 <img> 用）
images_dir = Path(__file__).parent.parent / "data" / "bulletin_images"
if images_dir.exists():
    app.mount("/static/bulletin_images", StaticFiles(directory=images_dir), name="bulletin_images")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "0.2.0"}
