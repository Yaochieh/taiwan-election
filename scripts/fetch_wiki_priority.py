"""對指定的高曝光人物優先補維基百科簡介。"""
import sys
import time
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_wiki_background import fetch_summary  # noqa

DB = Path(__file__).parent.parent / "data" / "db.sqlite"

NAMES = [
    "柯文哲","賴清德","蕭美琴","韓國瑜","黃國昌","侯友宜","趙少康","吳欣盈",
    "陳水扁","馬英九","蔡英文","李登輝","宋楚瑜","連戰","王金平","蘇貞昌",
    "賴瑞隆","王世堅","黃捷","沈伯洋","范雲","吳思瑤","蘇巧慧","鍾佳濱",
    "王鴻薇","徐巧芯","陳冠廷","張宏陸","蔡易餘","賴士葆","羅智強","傅崐萁",
    "陳亭妃","吳沛憶","蔡其昌","林楚茵","王正旭","林月琴","陳培瑜","王義川",
    "莊瑞雄","吳秉叡","林淑芬","郭昱晴","柯志恩","葛如鈞","翁曉玲","陳菁徽",
    "吳宗憲","林倩綺","陳永康","許宇甄","謝龍介","蘇清泉","張嘉郡","王育敏",
    "陳昭姿","吳春城","黃珊珊","邱顯智","林昶佐","顧立雄","鄭文燦","盧秀燕",
    "陳其邁","黃偉哲","柯建銘","江啟臣","鄭運鵬","林右昌","蔣萬安","郝龍斌",
]


def main():
    conn = sqlite3.connect(DB)
    done = skip = err = 0
    for name in NAMES:
        # 已經有就跳過
        ex = conn.execute(
            "SELECT 1 FROM candidates WHERE name=? AND length(COALESCE(background_source,''))>50 LIMIT 1",
            (name,),
        ).fetchone()
        if ex:
            skip += 1
            continue
        # 三種 title 嘗試
        result = None
        for t in (f"{name} (政治人物)", f"{name}_(政治人物)", name):
            result = fetch_summary(t)
            time.sleep(1.5)
            if result:
                break
        if not result:
            err += 1
            print(f"  ✗ {name}")
            continue
        extract, purl = result
        bg_text = f"{extract}\n\n（資料來源：中文維基百科 {purl}）"
        conn.execute(
            "UPDATE candidates SET background_source=? WHERE name=?",
            (bg_text, name),
        )
        conn.commit()
        done += 1
        print(f"  ✓ {name} ({len(extract)} 字)")
    print(f"\n✓ 新補 {done}; 已有 {skip}; 找不到 {err}")
    conn.close()


if __name__ == "__main__":
    main()
