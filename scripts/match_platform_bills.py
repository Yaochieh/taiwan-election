"""政見 × 立院提案 關鍵詞對照（P2，roadmap_2026H2.md）。

對 2024 當選立委：把政見逐條拆開，與其第 11 屆提案標題做關鍵詞對照，
寫入 platform_bill_matches 表。規則透明（下方 LEXICON），不用 LLM、可稽核。
呈現語意是「相關提案」，不是「已兌現」——是否兌現需人工判讀。

用法：python scripts/match_platform_bills.py [--dry-run]
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
BILLS = ROOT / "data" / "ly_bills.json"

# (政見面 pattern, 提案標題面 pattern, 標籤)
# 兩邊都命中才算一個 match；pattern 用 re.search
LEXICON: list[tuple[str, str, str]] = [
    (r"詐騙|反詐|詐欺", r"詐欺|詐騙", "反詐"),
    (r"囤房|房屋稅", r"房屋稅", "囤房稅"),
    (r"居住正義|社會住宅|社宅", r"住宅法|社會住宅", "社會住宅"),
    (r"租屋|租金|租賃", r"租賃住宅|租金", "租屋"),
    (r"都更|都市更新", r"都市更新", "都更"),
    (r"長照|長期照顧", r"長期照顧|長照", "長照"),
    (r"托育|托嬰|公托", r"托育|兒童及少年福利|幼兒教育及照顧", "托育"),
    (r"幼兒園|幼教|幼兒教育", r"幼兒教育及照顧", "幼教"),
    (r"育嬰|產假|陪產", r"性別平等工作|性別工作平等", "育嬰產假"),
    (r"生育|少子", r"人工生殖|優生保健|生育", "生育"),
    (r"護病比|護理", r"護理人員", "護理"),
    (r"健保", r"全民健康保險", "健保"),
    (r"藥師|藥事", r"藥事法|藥師", "藥事"),
    (r"醫療|醫師", r"醫療法|醫師法", "醫療"),
    (r"心理健康|心理諮商", r"心理健康|精神衛生", "心理健康"),
    (r"毒品", r"毒品危害防制", "毒品防制"),
    (r"酒駕", r"道路交通管理處罰條例|刑法第一百八十五條之三", "酒駕"),
    (r"交通安全|行人", r"道路交通|行人", "交通安全"),
    (r"虐童|兒虐|兒少", r"兒童及少年", "兒少保護"),
    (r"性暴力|性騷|跟蹤騷擾", r"性騷擾|跟蹤騷擾|性暴力", "性平防暴"),
    (r"勞保", r"勞工保險", "勞保"),
    (r"勞工退休|勞退", r"勞工退休金", "勞退"),
    (r"最低工資|基本工資", r"最低工資", "最低工資"),
    (r"職災", r"職業災害|職業安全", "職安"),
    (r"國民年金", r"國民年金", "國民年金"),
    (r"農民|老農|農業", r"農民健康保險|農業|老年農民", "農業"),
    (r"漁業|漁民", r"漁業", "漁業"),
    (r"原住民", r"原住民", "原住民"),
    (r"客家", r"客家", "客家"),
    (r"身障|身心障礙|無障礙", r"身心障礙", "身障"),
    (r"動物保護|流浪動物|毛小孩", r"動物保護", "動保"),
    (r"再生能源|綠能|光電", r"再生能源|電業法", "能源"),
    (r"核能|核電|以核養綠", r"核子反應器|核能", "核能"),
    (r"碳費|碳稅|淨零|減碳", r"氣候變遷|溫室氣體", "氣候"),
    (r"空污|空氣品質", r"空氣污染", "空污"),
    (r"食安|食品安全", r"食品安全", "食安"),
    (r"國防|兵役|志願役|後備", r"國防|兵役|全民防衛|軍人", "國防"),
    (r"退伍|榮民", r"退除役|退伍軍人", "退除役"),
    (r"學貸|就學貸款", r"就學貸款", "學貸"),
    (r"雙語|本土語言|母語", r"國家語言|雙語", "語言教育"),
    (r"補習班", r"補習及進修教育", "補教"),
    (r"青年創業|新創", r"中小企業|產業創新", "創業"),
    (r"個資", r"個人資料保護", "個資"),
    (r"資安", r"資通安全", "資安"),
    (r"人工智慧|AI", r"人工智慧", "AI"),
    (r"無人機", r"無人載具|無人機", "無人機"),
    (r"消防", r"消防", "消防"),
    (r"警察|警力|治安", r"警察|警械", "警政"),
    (r"財劃|財政收支", r"財政收支劃分", "財劃法"),
    (r"公投", r"公民投票", "公投"),
    (r"選罷|罷免", r"公職人員選舉罷免", "選罷法"),
    (r"捷運|軌道|鐵路", r"大眾捷運|鐵路法", "軌道"),
    (r"電動車|充電", r"電動汽車|充電", "電動車"),
    (r"觀光", r"觀光", "觀光"),
    (r"運動|體育", r"國民體育|運動產業", "體育"),
]
LEX = [(re.compile(p), re.compile(b), lab) for p, b, lab in LEXICON]

ITEM_SPLIT = re.compile(r"\n(?=\d+[\.、）\)])")


def split_items(content: str) -> list[str]:
    parts = [p.strip() for p in ITEM_SPLIT.split(content or "") if len(p.strip()) >= 8]
    return parts if len(parts) >= 2 else ([content.strip()] if content else [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bills_by_name: dict = json.loads(BILLS.read_text())
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    conn.execute("""CREATE TABLE IF NOT EXISTS platform_bill_matches (
        match_id INTEGER PRIMARY KEY,
        person_name TEXT NOT NULL,
        platform_id INTEGER NOT NULL,
        item_seq INTEGER NOT NULL,
        item_text TEXT NOT NULL,
        keyword TEXT NOT NULL,
        bill_no TEXT NOT NULL,
        bill_title TEXT NOT NULL,
        bill_status TEXT,
        bill_url TEXT,
        UNIQUE(platform_id, item_seq, keyword, bill_no)
    )""")
    conn.execute("DELETE FROM platform_bill_matches")

    # 2024 當選且有政見的立委
    rows = conn.execute("""
        SELECT DISTINCT c.name, pl.platform_id, pl.content
        FROM candidates c
        JOIN election_results er ON er.candidate_id=c.candidate_id AND er.election_id=c.election_id
        JOIN platforms pl ON pl.candidate_id=c.candidate_id AND pl.election_id=c.election_id
        WHERE c.election_id IN (50,51,52,53) AND er.elected=1
    """).fetchall()

    n_match = 0
    per_person: dict[str, int] = {}
    for r in rows:
        bills = bills_by_name.get(r["name"])
        if not bills:
            continue
        for seq, item in enumerate(split_items(r["content"]), 1):
            for p_pat, b_pat, label in LEX:
                if not p_pat.search(item):
                    continue
                for b in bills:
                    if not b_pat.search(b["title"]):
                        continue
                    if not args.dry_run:
                        conn.execute(
                            """INSERT OR IGNORE INTO platform_bill_matches
                               (person_name, platform_id, item_seq, item_text, keyword,
                                bill_no, bill_title, bill_status, bill_url)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (r["name"], r["platform_id"], seq, item[:300], label,
                             b["no"], b["title"][:200], b["status"], b["url"]))
                    n_match += 1
                    per_person[r["name"]] = per_person.get(r["name"], 0) + 1
    if not args.dry_run:
        conn.commit()
    total_people = len(per_person)
    print(f"✓ {total_people} 位立委、{n_match} 筆政見×提案對照")
    top = sorted(per_person.items(), key=lambda x: -x[1])[:10]
    print("對照數 top10:", top)
    conn.close()


if __name__ == "__main__":
    main()
