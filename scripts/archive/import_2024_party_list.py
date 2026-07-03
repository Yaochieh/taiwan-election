"""
從 113 屆全國不分區及僑居國外國民立法委員公報抽取各黨候選人名單，
並把 elected=1 標記給依不分區席次分配（Hare quota）排前 N 順位的候選人。

執行：
  python scripts/import_2024_party_list.py
"""
import re
import sqlite3
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
PDF = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf"

ELECTION_ID = 50  # 2024 不分區政黨

# 16 個有登記不分區的政黨（號次 1-16）
PARTIES_ORDERED = [
    "民主進步黨", "中國國民黨", "台灣民眾黨", "時代力量",
    "小民參政歐巴桑聯盟", "台灣綠黨", "台灣基進", "親民黨",
    "臺灣雙語無法黨", "台灣團結聯盟", "新黨", "司法改革黨",
    "制度救世島", "中華統一促進黨", "人民最大黨", "台灣維新",
]

# 不分區席次分配（Hare quota，已知結果）
SEATS = {
    "民主進步黨": 13,
    "中國國民黨": 13,
    "台灣民眾黨": 8,
}


def normalize_name(raw: str) -> str:
    """姓名在 PDF 中是 [字\n字\n字]，把換行去掉再 strip。"""
    return re.sub(r"\s+", "", raw)


def parse_pdf(pdf_path: Path) -> dict[str, list[str]]:
    """回傳 {party_name: [candidate_name 依序]}"""
    doc = fitz.open(pdf_path)
    full = "\n".join(p.get_text() for p in doc)
    doc.close()

    result: dict[str, list[str]] = {}
    for party in PARTIES_ORDERED:
        if party not in full:
            continue
        # 從 party 名稱往後抓到下一個 party 名稱（或文本結束）
        start = full.find(party)
        # 該政黨段落結束 = 下一個 party 名出現的位置
        end = len(full)
        for next_party in PARTIES_ORDERED:
            if next_party == party:
                continue
            idx = full.find(next_party, start + len(party))
            if idx >= 0 and idx < end:
                end = idx
        chunk = full[start:end]
        # 找 候選人：「名單次序」後面是 1\n字\n字\n字\n... 出生年月日
        # 但同個 chunk 可能有多個 entries
        # Pattern: ^(\d+)\n([一-鿿·\s]+?)\n出生年月日
        candidates = []
        for m in re.finditer(
            r"\n(\d{1,2})\n([一-鿿··・\s‧]+?)\n出生年月日", chunk
        ):
            rank = int(m.group(1))
            name = normalize_name(m.group(2))
            if name and 2 <= len(name) <= 15:
                candidates.append((rank, name))
        # dedup by rank, keep order
        candidates.sort()
        result[party] = [n for _, n in candidates]
    return result


def main():
    parties = parse_pdf(PDF)
    print(f"📋 解析到 {len(parties)} 個政黨的候選人")
    for party, names in parties.items():
        elected_count = SEATS.get(party, 0)
        marker = f" → 當選 {elected_count}/{len(names)}" if elected_count else f" → 0/{len(names)}"
        print(f"  {party}: {len(names)} 人{marker}")
        for i, n in enumerate(names[:elected_count]):
            print(f"    {i+1}. {n} ★")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    inserted = 0
    for party, names in parties.items():
        # 找 party_id
        party_row = conn.execute(
            "SELECT party_id FROM parties WHERE name = ?", (party,)
        ).fetchone()
        party_id = party_row["party_id"] if party_row else None
        elected_count = SEATS.get(party, 0)

        for rank, name in enumerate(names, start=1):
            elected = 1 if rank <= elected_count else 0
            # 是否已存在
            ex = conn.execute(
                "SELECT candidate_id FROM candidates WHERE election_id=? AND name=?",
                (ELECTION_ID, name),
            ).fetchone()
            if ex:
                cid = ex["candidate_id"]
                conn.execute(
                    "UPDATE candidates SET party_id=?, background=? WHERE candidate_id=?",
                    (party_id, f"不分區立委（{party} 第 {rank} 順位）", cid),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO candidates (election_id, name, party_id, background, district) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ELECTION_ID, name, party_id, f"不分區立委（{party} 第 {rank} 順位）", "不分區"),
                )
                cid = cur.lastrowid
                inserted += 1
            # 在 election_results 中寫一筆，district = '不分區', votes=0（個人不計票）
            er = conn.execute(
                "SELECT result_id FROM election_results "
                "WHERE election_id=? AND candidate_id=? AND district=?",
                (ELECTION_ID, cid, "不分區"),
            ).fetchone()
            if er:
                conn.execute(
                    "UPDATE election_results SET elected=? WHERE result_id=?",
                    (elected, er["result_id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO election_results "
                    "(election_id, candidate_id, district, votes, elected) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ELECTION_ID, cid, "不分區", 0, elected),
                )

    conn.commit()
    print(f"\n✓ 新增 {inserted} 位候選人，總共處理 {sum(len(v) for v in parties.values())} 人")
    conn.close()


if __name__ == "__main__":
    main()
