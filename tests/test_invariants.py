"""資料不變量測試 — 鎖定歷史上出過的膨脹/重複計票 bug，防止 re-import 回歸。

唯讀連 data/db.sqlite。歷史 bug：
- 總統縣市列 4x、鄉鎮列 3x 膨脹（fix_presidential_inflation.py 修過）
- 「全國」摘要列 + 縣市列同時 SUM 的 5x 膨脹
- 副總統列重複計票（正副各一列票數相同）
"""
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"

# 官方已知數字（中選會）
KNOWN = {
    # (election_id, candidate查詢名, district): votes
    "tsai_2020_national": 8_170_231,
    "tsai_2020_taipei": 875_854,
    "lai_2024_national": 5_586_019,
    "total_valid_2020": 14_300_940,  # 8170231 + 5522119 + 608590
}


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def presidential_ids(conn):
    return [r[0] for r in conn.execute(
        "SELECT election_id FROM elections WHERE type='presidential' "
        "AND status='completed' ORDER BY date").fetchall()]


def test_presidential_county_sum_equals_national(conn):
    """每屆總統、每位候選人：Σ縣市票 == 全國摘要列票（無 4x/5x 膨脹）"""
    for eid in presidential_ids(conn):
        rows = conn.execute("""
            SELECT candidate_id,
                   SUM(CASE WHEN district='全國' OR district LIKE '地區(0%' THEN votes END) AS national,
                   SUM(CASE WHEN district!='全國' AND district NOT LIKE '地區(0%' THEN votes END) AS county_sum
            FROM election_results WHERE election_id=? GROUP BY candidate_id
        """, (eid,)).fetchall()
        for r in rows:
            if r["national"] is None or r["county_sum"] is None:
                continue
            assert r["county_sum"] == r["national"], (
                f"election {eid} candidate {r['candidate_id']}: "
                f"縣市加總 {r['county_sum']} != 全國 {r['national']}")


def test_presidential_township_sum_equals_county(conn):
    """總統鄉鎮列加總 == 縣市列（無 3x 膨脹）。

    豁免 election 4（2000）：中選會原始資料的縣市摘要含驗票更正、
    鄉鎮明細未同步（18 組、最大差 1,159 票），非本平台 bug。
    """
    for eid in presidential_ids(conn):
        if eid == 4:
            continue
        rows = conn.execute("""
            SELECT tr.candidate_id, tr.county, SUM(tr.votes) AS t_sum,
                   (SELECT er.votes FROM election_results er
                    WHERE er.election_id=tr.election_id AND er.candidate_id=tr.candidate_id
                      AND er.district=tr.county) AS county_votes
            FROM township_results tr WHERE tr.election_id=?
            GROUP BY tr.candidate_id, tr.county
        """, (eid,)).fetchall()
        for r in rows:
            if r["county_votes"] is None:
                continue
            assert r["t_sum"] == r["county_votes"], (
                f"election {eid} cand {r['candidate_id']} {r['county']}: "
                f"鄉鎮加總 {r['t_sum']} != 縣市 {r['county_votes']}")


def test_known_official_numbers(conn):
    """已知官方數字抽查"""
    v = conn.execute("""
        SELECT er.votes FROM election_results er JOIN candidates c USING(candidate_id)
        WHERE er.election_id=48 AND c.name='蔡英文' AND er.district='全國'
    """).fetchone()[0]
    assert v == KNOWN["tsai_2020_national"]
    v = conn.execute("""
        SELECT er.votes FROM election_results er JOIN candidates c USING(candidate_id)
        WHERE er.election_id=48 AND c.name='蔡英文' AND er.district='臺北市'
    """).fetchone()[0]
    assert v == KNOWN["tsai_2020_taipei"]


def test_query_layer_no_double_count():
    """db.queries 彙總函式回傳正確總票數（副總統/摘要列去重）"""
    import sys
    sys.path.insert(0, str(ROOT))
    import db.queries as q
    df = q.get_candidates_by_election(48)
    assert int(df[df.name == "蔡英文"].votes.iloc[0]) == KNOWN["tsai_2020_national"]
    assert q.get_total_votes_by_election(48) == KNOWN["total_valid_2020"]
    trend = q.get_presidential_vote_trend()
    v2024 = trend[trend.candidate_name == "賴清德"].votes.max()
    assert int(v2024) == KNOWN["lai_2024_national"]


def test_completed_elections_have_results(conn):
    """completed 選舉必須有結果（豁免：89/90 大罷免，結果待匯入）"""
    exempt = {89, 90}
    rows = conn.execute("""
        SELECT e.election_id FROM elections e WHERE e.status='completed'
        AND NOT EXISTS (SELECT 1 FROM election_results er WHERE er.election_id=e.election_id)
    """).fetchall()
    bad = [r[0] for r in rows if r[0] not in exempt]
    assert not bad, f"completed 但無結果: {bad}"


def test_no_template_duplicate_platforms(conn):
    """同一場選舉不得有 ≥3 位候選人政見前 80 字完全相同（腦補模板特徵）"""
    rows = conn.execute("""
        SELECT election_id, substr(content,1,80) AS head, COUNT(*) AS n
        FROM platforms WHERE length(content) >= 80
        GROUP BY election_id, head HAVING n >= 3
    """).fetchall()
    assert not rows, f"疑似模板政見: {[(r['election_id'], r['n']) for r in rows]}"


def test_all_platforms_have_raw(conn):
    """所有政見都要有 content_raw（原始 OCR 來源）"""
    n = conn.execute("SELECT COUNT(*) FROM platforms WHERE content_raw IS NULL").fetchone()[0]
    assert n == 0, f"{n} 條政見沒有 content_raw"


def test_authenticity_audit_baseline():
    """audit_authenticity 不得出現超出 baseline 的新問題"""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts/audit_authenticity.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"稽核發現新問題:\n{r.stdout}"
