"""
批次匯入 2024 立委政見（文字 + 圖片）。

對應關係：
  PDF 路徑                                                     | DB district
  02區域立法委員/02臺北市/第1選舉區/臺北市立委第1選舉區.pdf      | 臺北市第01選區
  02區域立法委員/16新竹市/.../新竹市立委選舉.pdf                  | 新竹市第01選區
  03平地原住民立法委員/全國平地原住民立法委員.pdf                  | (全國)
  04山地原住民立法委員/全國山地原住民立法委員.pdf                  | (全國)
  05全國不分區/.../全國不分區及僑居國外國民立法委員.pdf             | (不分區)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db.queries import get_connection
from scripts.import_platforms import import_pdf, init_schema
from scripts.extract_bulletin_images import extract_pdf, update_db as update_image_db

BULLETIN_ROOT = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆"
URL_BASE = "https://bulletin.cec.gov.tw/01選舉公報/02立法委員/113年第11屆"

# 立委選舉 election_id (2024)
ELECTION_REGIONAL = 51   # 區域
ELECTION_LOWLAND = 53    # 平地原住民
ELECTION_HIGHLAND = 52   # 山地原住民
ELECTION_PARTY = 50      # 不分區政黨

# 阿拉伯／中文數字映射
CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def parse_district_from_path(pdf_path: Path) -> tuple[str | None, int | None]:
    """從 PDF 路徑解析出縣市 + 選舉區號。

    範例：
      .../02臺北市/第1選舉區/臺北市立委第1選舉區.pdf  → ("臺北市", 1)
      .../17新竹市/新竹市立委/01新竹市立委選舉.pdf  → ("新竹市", 1)
      .../14苗栗縣/第1選舉區/苗栗縣立委第1選舉區.pdf  → ("苗栗縣", 1)
    """
    parts = pdf_path.parts
    # 從路徑找縣市
    city = None
    for p in parts:
        m = re.match(r"^\d{2}(.+市|.+縣)$", p)
        if m:
            city = m.group(1)
            break

    # 從路徑或檔名找選舉區號
    region_num = None
    for p in parts:
        m = re.search(r"第(\d+|[一二三四五六七八九十]+)選舉區", p)
        if m:
            n = m.group(1)
            region_num = int(n) if n.isdigit() else CN_NUM.get(n)
            break

    # 沒選區號（小縣市只有一個選舉區）默認 1
    if city and region_num is None:
        region_num = 1

    return city, region_num


def db_district_for(city: str | None, region_num: int | None) -> str | None:
    """組合 DB 中的 district 字串。"""
    if not city or region_num is None:
        return None
    return f"{city}第{region_num:02d}選區"


def main():
    if not BULLETIN_ROOT.exists():
        print(f"找不到 {BULLETIN_ROOT}", file=sys.stderr)
        sys.exit(1)

    # ── 區域立委 ─────────────────────────────────────────────────────────────
    regional_pdfs = sorted(
        p for p in BULLETIN_ROOT.glob("02區域立法委員/**/*.pdf")
        # 排除「投開票所」這種非政見 PDF
        if "投開票所" not in p.name and "罷免" not in p.name
    )
    print(f"📋 找到 {len(regional_pdfs)} 個區域立委公報 PDF")

    success_regional = 0
    failed_regional = 0
    for pdf in regional_pdfs:
        city, region_num = parse_district_from_path(pdf)
        district = db_district_for(city, region_num)
        if not district:
            print(f"  ⚠️  無法解析 district：{pdf.relative_to(BULLETIN_ROOT)}")
            failed_regional += 1
            continue

        # 確認 DB 有這個 district
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM election_results "
                "WHERE election_id = ? AND district = ?",
                (ELECTION_REGIONAL, district)
            ).fetchone()
            if row["c"] == 0:
                print(f"  ⚠️  DB 找不到 district [{district}]：{pdf.name}")
                failed_regional += 1
                continue

        rel = pdf.relative_to(ROOT)
        source_url = f"{URL_BASE}/02區域立法委員/{pdf.parent.relative_to(BULLETIN_ROOT / '02區域立法委員')}/{pdf.name}"

        # ── 文字 ──
        try:
            import_pdf(pdf, ELECTION_REGIONAL, source_url, dry_run=False,
                       district=district, parser="v1")
        except Exception as e:
            print(f"  ✗ 文字匯入失敗 {district}: {e}")

        # ── 圖片 ──
        try:
            with get_connection() as conn:
                names = [
                    r["name"] for r in conn.execute("""
                        SELECT DISTINCT c.name FROM election_results er
                        JOIN candidates c ON er.candidate_id = c.candidate_id
                        WHERE er.election_id = ? AND er.district = ?
                    """, (ELECTION_REGIONAL, district)).fetchall()
                ]
            results = extract_pdf(pdf, ELECTION_REGIONAL, names, max_pages=2)
            update_image_db(results, ELECTION_REGIONAL, source_url)
        except Exception as e:
            print(f"  ✗ 圖片擷取失敗 {district}: {e}")

        success_regional += 1

    # ── 不分區政黨 ───────────────────────────────────────────────────────────
    party_pdf = BULLETIN_ROOT / "05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf"
    if party_pdf.exists():
        print(f"\n📋 不分區政黨：{party_pdf.name}")
        # 不分區的候選人比較複雜（每政黨多人），先記 source 就好
        with get_connection() as conn:
            init_schema(conn)
            conn.execute("""
                INSERT INTO platform_sources
                    (candidate_id, election_id, source_type, url, local_path, description, fetched_at)
                SELECT c.candidate_id, ?, 'cec_bulletin', ?, ?, ?, datetime('now')
                FROM candidates c WHERE c.election_id = ?
            """, (
                ELECTION_PARTY,
                f"{URL_BASE}/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf",
                str(party_pdf.relative_to(ROOT)),
                "中選會選舉公報（不分區政黨）",
                ELECTION_PARTY,
            ))
            conn.commit()
        print("  ✓ 已為所有不分區政黨候選人記錄 source")

    print()
    print(f"✓ 區域立委：成功 {success_regional} 選區，失敗 {failed_regional}")


if __name__ == "__main__":
    main()
