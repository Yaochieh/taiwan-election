"""一次性：清 2026-06 腦補事故遺留在 platform_targets 的殘留（2026-10-27 發現）。

背景：2026-06 腦補政見已刪除重做，但當時由「人工潤稿」政見抽出的部分量化承諾
沒有跟著刪，描述仍是捏造文字（例：侯友宜「8 年蓋 25 萬戶社宅」）。

判定方式：逐條對照來源政見的原始 OCR，以及 2024 總統／不分區公報全文 OCR
（content_raw 有 8,000 字截斷，不能只看 content_raw）。

A. 承諾本身不在公報 → 刪除（連帶刪 progress／disputes，FK cascade）
B. 承諾是真的、描述是捏造或改寫 → 描述改為公報原文照抄
C. T31 賴清德社宅：公報寫「25萬戶社會住宅、25萬戶包租代管」為兩個目標，
   原進度把包租代管算進社宅 → 改為只計直接興辦，基準同步改為直接興辦口徑

用法：python scripts/fix_target_remnants_2026_10.py [--dry-run]
跑完移到 scripts/archive/。
"""
import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"

# A：由 main() 的 --delete 參數帶入（OCR 全文確認後才決定），不在此寫死
# B：公報原文照抄（來源 platform content_raw，已人工比對）
DESCRIPTIONS = {
    31: "推動「囤房稅2.0」，至2032年累計達成興辦25萬戶社會住宅、25萬戶包租代管、50萬戶租金補貼，以協助百萬租屋家戶",
    32: "提高教育經費編列下限1%，預估成長300億。",
    33: "1萬育兒津貼，扶養12歲以下子女，扣除額提高50%。",
    29: "增加消防、防救災預算，提高至少50%",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", default="", help="逗號分隔：確認為腦補、要刪除的 target_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    delete_ids = [int(x) for x in args.delete.split(",") if x.strip()]

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys=ON")

    # 驗證 B 的原文確實在來源 OCR 裡（照抄，不容改寫）
    for tid, desc in DESCRIPTIONS.items():
        raw = conn.execute(
            "SELECT p.content_raw FROM platform_targets t JOIN platforms p "
            "ON p.platform_id = t.source_platform_id WHERE t.target_id = ?", (tid,)).fetchone()[0]
        flat = raw.replace("\n", "")
        assert desc.replace("「", "").replace("」", "")[:20] in flat.replace("「", "").replace("」", ""), \
            f"target {tid} 描述不在原文：{desc[:20]}"

    for tid in delete_ids:
        r = conn.execute("SELECT person_name, title, flagship FROM platform_targets WHERE target_id=?",
                         (tid,)).fetchone()
        print(f"A 刪除 {tid} {r[0]}「{r[1]}」{'（旗艦）' if r[2] else ''}")
        if not args.dry_run:
            conn.execute("DELETE FROM platform_targets WHERE target_id=?", (tid,))

    for tid, desc in DESCRIPTIONS.items():
        print(f"B 描述改原文 {tid}：{desc[:30]}…")
        if not args.dry_run:
            conn.execute(
                "UPDATE platform_targets SET description=?, "
                "verification_note=TRIM(COALESCE(verification_note,'') || ' 描述已於 2026-10-27 改為公報原文照抄（原描述為 2026-06 人工潤稿殘留）') "
                "WHERE target_id=?", (desc, tid))

    # C：T31 只計直接興辦。數字皆取自既有進度 note 所載之內政部／國土署統計
    print("C T31 改為直接興辦口徑：基準 105,125；2026-06-30 進度 125,441；2025 年底 122,680")
    if not args.dry_run:
        conn.execute("UPDATE platform_targets SET baseline_value=105125 WHERE target_id=31")
        conn.execute("DELETE FROM platform_progress_breakdown WHERE progress_id=14 AND label='包租代管'")
        conn.execute("""UPDATE platform_target_progress SET current_value=125441, note=?
                        WHERE progress_id=14""", (
            "內政部社宅專區統計（截至2026-06-30）直接興建達成125,441戶"
            "（完工46,673+興建中62,591+決標待開工16,177）。公報政見將「25萬戶社會住宅」與"
            "「25萬戶包租代管」列為兩個目標，故本承諾只計直接興辦，不含包租代管有效契約"
            "114,737戶（2026-10-27 修正；先前誤將兩者合計為240,178戶）。"
            "基準：就任初期（113年7月底）直接興辦105,125戶（國土署）。",))
        conn.execute("""UPDATE platform_target_progress SET current_value=122680, note=?
                        WHERE progress_id=2""", (
            "截至2025年底全國社宅直接興辦122,680戶（內政部統計），2016年起累計，含蔡政府時期。"
            "包租代管104,803戶為另一項承諾，不計入（2026-10-27 修正）。"
            "基準：就任初期（113年7月底）直接興辦105,125戶（國土署）。",))

    if not args.dry_run:
        conn.commit()
    conn.close()
    print("完成" + ("（dry-run 未寫入）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
