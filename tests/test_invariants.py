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
    """completed 選舉必須有結果（一般選舉在 election_results，罷免在 recall_results）"""
    rows = conn.execute("""
        SELECT e.election_id FROM elections e WHERE e.status='completed'
        AND NOT EXISTS (SELECT 1 FROM election_results er WHERE er.election_id=e.election_id)
        AND NOT EXISTS (SELECT 1 FROM recall_results rr WHERE rr.election_id=e.election_id)
    """).fetchall()
    bad = [r[0] for r in rows]
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


def test_progress_breakdown_sums_to_current_value():
    """口徑拆解的各項總和必須等於該筆進度的 current_value。

    拆解是為了把「完工／興建中／待開工／包租代管」攤開（2026-09 回饋 R1）。
    若總和對不上，代表漏了項目或數字抄錯，畫出來的分段進度條會自相矛盾。
    """
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
            SELECT b.progress_id, p.current_value, SUM(b.value) AS total
            FROM platform_progress_breakdown b
            JOIN platform_target_progress p ON p.progress_id = b.progress_id
            GROUP BY b.progress_id
        """).fetchall()
    assert rows, "沒有任何拆解資料——若已移除請一併刪除本測試"
    for pid, current, total in rows:
        assert abs(current - total) < 0.5, (
            f"progress {pid} 拆解總和 {total} != current_value {current}"
        )


def test_progress_breakdown_has_delivered_item():
    """每筆拆解都要有至少一項標記為已交付，否則 delivered_value 會是 0 而非 None，
    前端會顯示「其中完工 0」這種無意義的內容。"""
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
            SELECT progress_id, SUM(delivered) FROM platform_progress_breakdown
            GROUP BY progress_id
        """).fetchall()
    for pid, n in rows:
        assert n >= 1, f"progress {pid} 的拆解沒有任何 delivered=1 項目"


def test_target_disputes_well_formed():
    """口徑爭議標註（回饋 R2）：只能掛在旗艦承諾上，每筆都要有來源網址與原文引句。

    引句是讀者判斷爭議的唯一依據，沒有引句等於只貼一個連結叫人自己去找；
    掛到非旗艦承諾則代表範圍失控（R2 決定只做旗艦）。
    """
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
            SELECT d.dispute_id, d.url, d.quote, d.source_type, d.quote_verified, t.flagship
            FROM platform_target_disputes d
            LEFT JOIN platform_targets t ON t.target_id = d.target_id
        """).fetchall()
    for did, url, quote, stype, verified, flagship in rows:
        assert flagship == 1, f"dispute {did} 掛在非旗艦承諾上"
        assert url and url.startswith("http"), f"dispute {did} 沒有有效 url"
        assert quote and len(quote.strip()) >= 10, f"dispute {did} 引句太短或空白"
        assert stype in {"oversight", "factcheck", "ngo", "media"}, f"dispute {did} source_type={stype}"
        assert verified in {"auto", "manual"}, f"dispute {did} 引句未經核對"


def test_announce_value_has_source():
    """政見公布時數值（2026-10 回饋）：有數值就必須有統計時點與來源網址。"""
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
            SELECT target_id, announce_date, announce_source_url FROM platform_targets
            WHERE announce_value IS NOT NULL
        """).fetchall()
    assert rows, "沒有任何政見公布時數值——若已移除欄位請一併刪除本測試"
    for tid, d, url in rows:
        assert d, f"target {tid} 有公布時數值但沒有統計時點"
        assert url and url.startswith("http"), f"target {tid} 有公布時數值但沒有來源"


# ── 2026 選舉公報候選人資料（extract_2026_bulletin_candidates.py）──────────────

def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def test_bulletin_profiles_have_source(conn):
    """每筆公報資料都要有來源 PDF 與 URL（資料真實性鐵律 2）。"""
    if not _has_table(conn, "candidate_bulletin_profiles"):
        pytest.skip("尚未匯入")
    bad = conn.execute(
        "SELECT candidate_id FROM candidate_bulletin_profiles "
        "WHERE source_url IS NULL OR source_url NOT LIKE 'https://bulletin.cec.gov.tw/%' "
        "   OR source_pdf IS NULL").fetchall()
    assert not bad, f"公報資料缺來源：{[r[0] for r in bad][:10]}"


def test_bulletin_ballot_no_unique_per_district(conn):
    """同一場、同一選區不可有重複號次（重複 = 抽取把人對錯欄）。"""
    if not _has_table(conn, "candidate_bulletin_profiles"):
        pytest.skip("尚未匯入")
    dup = conn.execute(
        "SELECT c.election_id, c.district, bp.ballot_no, COUNT(*) FROM candidate_bulletin_profiles bp "
        "JOIN candidates c USING(candidate_id) WHERE bp.ballot_no IS NOT NULL "
        "GROUP BY 1,2,3 HAVING COUNT(*) > 1").fetchall()
    assert not dup, f"號次重複：{[tuple(r) for r in dup][:10]}"


def test_2026_photo_files_exist(conn):
    """2026 候選人的 photo_path 必須指向存在的檔案。"""
    rows = conn.execute("SELECT candidate_id, photo_path FROM candidates "
                        "WHERE election_id BETWEEN 77 AND 82 AND photo_path IS NOT NULL").fetchall()
    missing = [r[0] for r in rows if not (ROOT / r[1]).exists()]
    assert not missing, f"照片檔不存在：{missing[:10]}"


def test_2026_platforms_have_bulletin_source(conn):
    """2026 政見必須是公報原文且附公報 URL。"""
    bad = conn.execute("SELECT platform_id FROM platforms WHERE election_id BETWEEN 77 AND 82 "
                       "AND (source_url IS NULL OR content_raw IS NULL)").fetchall()
    assert not bad, f"2026 政見缺來源：{[r[0] for r in bad][:10]}"


def test_2026_image_platforms_have_file_and_source(conn):
    """2026 圖片政見：檔案存在、附公報 URL。"""
    rows = conn.execute("SELECT candidate_id, local_path, url FROM platform_sources "
                        "WHERE election_id BETWEEN 77 AND 82 AND source_type='image_platform'").fetchall()
    bad = [r[0] for r in rows if not r[2] or not r[1] or not (ROOT / r[1]).exists()]
    assert not bad, f"圖片政見缺檔案或來源：{bad[:10]}"


def test_election_districts_match_announcement(conn):
    """選舉區範圍：每筆有來源、名額為正、範圍沒有被斷頁切掉（結尾不是「、」「之」）。"""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='election_districts'").fetchone():
        return
    bad = conn.execute("SELECT district FROM election_districts WHERE source_url IS NULL "
                       "OR seats IS NULL OR seats <= 0 OR area LIKE '%、' OR area LIKE '%之'").fetchall()
    assert not bad, f"選舉區資料異常：{[r[0] for r in bad]}"


def test_village_chiefs_have_roster_source(conn):
    """村里長（登記名冊匯入）：每筆都標來源與登記標記。"""
    bad = conn.execute("""SELECT c.candidate_id FROM candidates c JOIN elections e USING (election_id)
                          WHERE e.type='village_chief' AND (c.official_source IS NULL
                                OR c.background IS NOT '[登記中未經審定]')""").fetchall()
    assert not bad, f"村里長缺來源或標記：{[r[0] for r in bad][:10]}"


def test_council_2022_one_row_per_candidate(conn):
    """2022 議員（import_council_2022.py）：候選人以 (姓名, 選區) 區分，每人恰一筆得票、
    選區名不得是未解析的「地區(…)」代碼，當選數等於中選會 elcand「*」合計（直轄市 376、縣市 530）。"""
    rows = conn.execute("""SELECT e.name, COUNT(*) n, COUNT(DISTINCT r.candidate_id) c, SUM(r.elected) won,
                                  SUM(r.district LIKE '地區(%') raw
                           FROM election_results r JOIN elections e USING (election_id)
                           WHERE e.type='council' AND e.date='2022-11-26' GROUP BY e.name""").fetchall()
    if not rows:
        return
    got = {r["name"]: r for r in rows}
    for r in rows:
        assert r["n"] == r["c"], f"{r['name']} 有候選人被併成多筆"
        assert not r["raw"], f"{r['name']} 有未解析選區代碼"
    assert got["111年直轄市議員選舉"]["won"] == 376
    assert got["111年縣市議員選舉"]["won"] == 530
