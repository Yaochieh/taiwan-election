"""議題缺口分析：社會嚴重度(公開統計) vs 政治關注度(政見提及)。"""
import json
from pathlib import Path

from fastapi import APIRouter

from db.queries import get_connection

router = APIRouter()

DATA = Path(__file__).parent.parent.parent / "data"


def _attention(keywords: list[str]) -> dict:
    """算多少政見/候選人提及這些關鍵字（只算有政見的）。"""
    like = " OR ".join(["p.content LIKE ?"] * len(keywords))
    params = [f"%{k}%" for k in keywords]
    with get_connection() as conn:
        row = conn.execute(
            f"""SELECT COUNT(DISTINCT p.platform_id) platforms,
                       COUNT(DISTINCT p.candidate_id) people
                FROM platforms p WHERE {like}""",
            params,
        ).fetchone()
        total_people = conn.execute(
            "SELECT COUNT(DISTINCT candidate_id) FROM platforms"
        ).fetchone()[0]
    return {
        "platforms": row["platforms"],
        "people": row["people"],
        "total_people": total_people,
        "pct": round(row["people"] / total_people * 100, 1) if total_people else 0,
    }


@router.get("/overview")
def issue_overview():
    """14 主題政治關注度排名（低 = 潛在缺口）。"""
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(DISTINCT candidate_id) FROM platforms"
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT t.name, t.icon,
                      COUNT(DISTINCT l.platform_id) AS platforms,
                      COUNT(DISTINCT c.name) AS people
               FROM platform_topics t
               LEFT JOIN platform_topic_links l ON l.topic_id = t.topic_id
               LEFT JOIN platforms p ON p.platform_id = l.platform_id
               LEFT JOIN candidates c ON c.candidate_id = p.candidate_id
               GROUP BY t.topic_id
               ORDER BY platforms ASC"""
        ).fetchall()
    return {
        "total_people": total,
        "topics": [
            {
                "name": r["name"],
                "icon": r["icon"],
                "platforms": r["platforms"],
                "people": r["people"],
                "pct": round(r["people"] / total * 100, 1) if total else 0,
            }
            for r in rows
        ],
    }


@router.get("/fertility")
def fertility_gap():
    """少子化議題缺口：出生數趨勢 + 政治關注度。"""
    births_file = DATA / "births.json"
    births = []
    if births_file.exists():
        raw = json.loads(births_file.read_text())
        births = sorted(
            ({"year": v["ad"], "births": v["births"]} for v in raw.values()),
            key=lambda x: x["year"],
        )
    attention = _attention(["少子", "生育", "托育", "托嬰", "育兒"])
    first = births[0]["births"] if births else None
    last = births[-1]["births"] if births else None
    drop_pct = round((first - last) / first * 100, 1) if first and last else None
    return {
        "topic": "少子化",
        "severity_source": "內政部戶政司 ODRP028 出生數統計",
        "births": births,
        "drop_pct": drop_pct,
        "attention": attention,
        "attention_keywords": ["少子化", "生育", "托育", "托嬰", "育兒"],
    }
