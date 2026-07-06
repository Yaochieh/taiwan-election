"""API smoke test — 每個 router 的主要端點回 200 且有關鍵欄位。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from api.main import app  # noqa: E402

client = TestClient(app)

SMOKE = [
    ("/health", None),
    ("/elections", None),
    ("/elections/cycles", None),
    ("/elections/48", "name"),
    ("/elections/48/results", None),
    ("/elections/48/totals", None),
    ("/elections/48/total-votes", None),
    ("/elections/48/townships", None),
    ("/candidates/search?q=蔡英文", None),
    ("/parties", None),
    ("/parties/seats?election_id=51", None),
    ("/platforms/elections", None),
    ("/platforms/elections/51", None),
    ("/trends/presidential", None),
    ("/trends/presidential/county-winners", None),
    ("/trends/mayoral/county-winners", None),
    ("/mayoral/history", None),
    ("/legislature/trend/seats", None),
    ("/search?q=蔡英文", None),
    ("/people/蔡英文", "name"),
    ("/people/蔡英文/targets", None),
    ("/topics", None),
    ("/topics/交通", None),
    ("/issues/overview", None),
    ("/issues/fertility", None),
]


@pytest.mark.parametrize("path,key", SMOKE, ids=[p for p, _ in SMOKE])
def test_endpoint(path, key):
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
    data = r.json()
    if key:
        assert key in data, f"{path} 缺 {key}"


def test_election_totals_no_inflation():
    """/elections/48/total-votes 回 2020 實際有效票數（歷史 bug: 2x/5x）"""
    r = client.get("/elections/48/total-votes")
    assert r.status_code == 200
    body = r.json()
    total = body["total_votes"] if isinstance(body, dict) else body
    assert total == 14_300_940, f"2020 總統有效票應為 14,300,940，got {total}"


def test_unknown_candidate_404():
    r = client.get("/candidates/99999999")
    assert r.status_code == 404


def test_unknown_person_404():
    r = client.get("/people/不存在的人xyz")
    assert r.status_code == 404


def test_unknown_topic_404():
    for suffix in ("", "/stats", "/targets"):
        r = client.get(f"/topics/不存在主題xyz{suffix}")
        assert r.status_code == 404, f"/topics/...{suffix} -> {r.status_code}"


def test_unknown_legislature_year_404():
    r = client.get("/legislature/1888")
    assert r.status_code == 404


def test_candidate_platforms_filtered():
    """政見端點只回該候選人的條目"""
    r = client.get("/platforms/elections/51")
    assert r.status_code == 200
    rows = r.json()
    assert rows, "election 51 應有政見"
    cid = rows[0]["candidate_id"]
    r2 = client.get(f"/platforms/candidates/{cid}?election_id=51")
    assert r2.status_code == 200
    assert all(p["candidate_id"] == cid for p in r2.json())


def test_election_milestones():
    """選舉時程里程碑：最近投票日 2026-11-28 應有 12 筆且含投票日"""
    r = client.get("/elections/milestones")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 12
    assert rows[-1]["date"] == "2026-11-28"
    assert all(m["source_url"].startswith("https://web.cec.gov.tw") for m in rows)


def test_flagship_closed_target_uses_final_value():
    """結案 target 的 latest 取最終修正值（同日多筆以 progress_id 最新為準）——柯文哲 684 應為 5,062 而非 12,926"""
    r = client.get("/platforms/targets/flagship")
    assert r.status_code == 200
    ko = next(t for t in r.json() if t["target_id"] == 684)
    assert ko["status"] == "failed"
    assert ko["latest_value"] == 5062.0
    assert ko["progress_pct"] < 100


def test_recall_results():
    """罷免結果：33案全數否決、7案達門檻、每案同意+不同意=有效票"""
    r = client.get("/elections/recalls")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 33
    assert all(x["passed"] == 0 for x in rows)
    assert sum(x["threshold_met"] for x in rows) == 7
    for x in rows:
        if x["valid_votes"] is not None:
            assert x["agree_votes"] + x["disagree_votes"] == x["valid_votes"], x["target_name"]
    ko = next(x for x in rows if x["target_name"] == "高虹安")
    assert ko["agree_votes"] == 86291 and ko["disagree_votes"] == 124360
