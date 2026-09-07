# 正至 · 台灣選舉資訊平台（後端）

雙倉庫專案：本 repo 是 **API 後端** — Python + FastAPI + SQLite。
前端在 `~/Desktop/Projects/taiwan-election-web`（Next.js + TypeScript）。
線上：
- 前端 https://taiwan-election-web.vercel.app
- API  https://web-production-f7c522.up.railway.app

## 開發環境

```
python 3.11+
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
sqlite3 data/db.sqlite              # 直接看資料
```

## 目錄結構

```
api/
  main.py             FastAPI 入口、CORS、靜態資源
  routers/            各功能 router (elections/people/topics/…)
  utils.py            df_to_records 等 helper
db/
  queries.py          所有 SQL 查詢函式（pandas + sqlite3）
models/               Pydantic 回應模型
scripts/              可重跑的 pipeline 與工具（手冊：scripts/README.md）
  archive/            已跑完的一次性腳本，保留供查證，不要重跑
tests/                資料不變量 + API smoke（commit DB 前必跑）
docs/                 roadmap_2026H2.md（規劃單一來源）/ data_model_v2 / sitemap
.github/workflows/    ci.yml（稽核+測試）、track-progress.yml（每日抓進度開 PR）
data/
  db.sqlite           主資料庫（**commit in repo**, Railway 重 deploy 時更新）
  votedata.zip        中選會原始 CSV（**不要 unzip**，腳本動態讀）
  bulletins/          選舉公報 PDF
  bulletin_pages*/    OCR 用渲染 PNG
```

## 資料 schema 重點

**選舉核心**
- `elections` — 91 場（presidential / legislative / mayoral / council），含 `status='scheduled'` 的 2026
- `candidates` — 9,045 人，可同名跨選舉（用 candidate_id 區分）
- `election_results` — 候選人 × 選區 × 票數，含「全國」摘要列
- `township_results` — 總統選舉鄉鎮市區層級（18,418 列，1996–2024）
- `recall_results` — 2025 大罷免 33 案（審定票數／同意門檻／來源）
- `election_milestones` — 選舉日曆（中選會法定時程）
- `seats` / `platform_categories` — 仍被 `/parties/seats`、`import_platforms.py` 引用，**不要刪**（R4 決策）

**政見與追蹤鏈**（本專案主軸）
```
platforms → platform_targets → platform_target_progress → topic_data_sources
   ↑OCR/LLM      ↑量化承諾           ↑實際進度值            ↑政府開放資料
```
- `platforms` 883 條（立委／縣市長／2024 總統），有 `content_raw`（原始 OCR，可驗證）
- `platform_topic_links` + `platform_topics` — 14 主題標籤
- `platform_targets` 1,692 筆 — 量化承諾。關鍵欄位：
  `extraction_method`（llm / regex，**兩管線隔離**）、`tense`（past 政績 / future 承諾）、
  `status`（in_progress / achieved / failed）、`is_flagship`、`baseline_value` / `target_date`
- `platform_target_progress` 23 筆 + `platform_progress_sources` 34 筆 — 旗艦承諾的實際進度與來源
- `platform_bill_matches` — 立委政見 × 立院提案對照（65 位／1,118 筆）
- `platform_sources` — 政見來源（公報檔名／URL）
- `topic_data_sources` 20 筆 — 主題 → 可追蹤的政府開放資料 URL（**偏少，需持續養**）

## ★ 資料真實性鐵律（最高優先，違反等於專案失敗）

2026-06 曾發生重大事故：政見資料被用模型內建知識「腦補」寫出（例：蔣萬安
「8年蓋25萬戶社宅」），265 條政見 + 2,349 筆假 targets 全數刪除重來。
自此本專案的第一原則是：

1. **禁止手寫腦補**。任何政見／學經歷／數字，只能來自真實選舉公報 OCR、
   官方 API、或明確標注的公開來源。**不確定就留空，寧缺勿假。**
2. **一切標來源**。`platforms.source_url`、`candidates.source_url` /
   `background_source`、`platform_targets.source_url`、
   `platform_progress_sources`。人工潤稿要在 `platforms.note` 標
   `[人工潤稿 by Claude YYYY-MM-DD]`。
3. **LLM 產出必須對原文驗證**。`extract_*_bio_safe.py` 用 80% 4-gram 重疊
   比對原始 OCR，不過就拒絕（縣市長版曾 14/14 全拒 = 機制正常，不是壞掉）。
   2026-07 有 8 條政見複驗重疊度 10–59%，依原則全刪。
4. **commit DB 前必跑稽核**：
   ```
   python scripts/audit_authenticity.py     # 5 項檢查，exit 1 = 有新問題
   python -m pytest tests/ -q               # 資料不變量 + API smoke
   ```
   修完舊帳才用 `--update-baseline` 更新 `scripts/audit_baseline.json`。
   `.github/workflows/ci.yml` 也會跑。
5. **兩條 targets 抽取管線不可互相刪**：`llm_extract_targets.py`（主力）與
   `extract_platform_targets.py`（regex，稽核／dry-run 用）。各自只能刪
   `extraction_method` 是自己的 rows —— 絕不可無條件
   `DELETE WHERE auto_extracted=1`（曾誤刪 1,414 筆）。
6. **DB 可還原**：`git show HEAD:data/db.sqlite` 隨時取回上一版。

## 重要常識

1. **「全國」vs 縣市重複 SUM** — `election_results` 對總統選舉同時有
   `district='全國'` 與 22 個縣市 row（票數相同），任何 `SUM(votes)` 都要
   `WHERE district != '全國' AND district NOT LIKE '地區(0%'` 否則會
   5x 膨脹。`get_person_profile`/`search_candidates`/
   `get_presidential_vote_trend` 都用 COALESCE+CASE pattern 處理。
2. **「臺」字 vs「台」字** — DB 用「臺」(U+81FA)。前端 GeoJSON 用「台」。
   `format.ts` 的 `GEO_NAME_MAP` 做 4 個直轄市 mapping。
3. **副總統 background** — 2012/2016/2020 的副總統 candidate.background
   已修為「副總統」，前端用此判斷 正/副 配對。
4. **舊式 `地區(N, 0, 0)` district** — 早期 import 留下，2009 council 仍有
   `地區(3/4, 0, 0)`。新資料 (2010+) 都已 normalize 為縣市名。
5. **OCR 結果品質** — 多欄式 PDF 不同候選人欄位可能混雜。腳本
   `clean_ocr_noise.py` 過濾「性別：」「出生年月日：」等表頭雜訊；
   `recut_2024_legislative_columns.py` 用 x 座標重新分欄（已跑過）。
6. **PaddleOCR 很慢** — 每頁 30–60 秒，每屆全選區公報 OCR 跑 3-6 小時。
   背景跑 + DB 持續寫入；中斷只損失尚未 commit 的 row。
7. **★ 地名變遷對照表** — 比較跨年資料前一定要先 normalize：

   | 現代名 | 歷史名 | 升格 / 改名年 |
   |---|---|---|
   | 新北市 | 臺北縣 | 2010-12-25 升格 |
   | 桃園市 | 桃園縣 | 2014-12-25 升格 |
   | 臺中市 | 臺中縣 + 臺中市（省轄） | 2010-12-25 縣市合併 |
   | 臺南市 | 臺南縣 + 臺南市（省轄） | 2010-12-25 縣市合併 |
   | 高雄市 | 高雄縣 + 高雄市（直轄） | 2010-12-25 縣市合併 |
   | 臺北市 | 臺北市（省轄→直轄） | 1967-07-01 升格 |
   | 連江縣 | — | 一直叫連江縣（馬祖） |

   ★ 跨年熱力圖／政黨版圖／長條比較圖一定要套這張表。
   - 後端：`get_presidential_county_winners()` / `get_mayoral_county_winners()`
     已用 CASE WHEN 在 SQL 層 normalize；
   - 前端：`/parties/[name]` 的「縣市政治版圖」用 `COUNTY_MERGE` map；
   - 注意：1967 年前的「臺北市」≠ 現在臺北市範圍（含士林/北投/南港/內湖/景美/木柵 6 鄉鎮是1967 合併進來的），有總統選舉前後可能要再細分但目前不處理。

8. **★ 總統選舉每組正副各有獨立 row** — `election_results` 對總統選舉
   每位 candidate（正、副都算）都有一筆每縣市票數，且兩人票數相同。
   - 計算縣市總票數時，**必須過濾 `c.background='副總統'`**，否則票數會
     ×2。
   - 前端 `vote-map.tsx` 的 `focusByCounty` 和 `winnerByCounty` 都要小心；
     `winnerByCounty` 用「同票同黨 dedup」對也算過濾掉，`focusByCounty`
     需明確 `filter(r => r.background !== '副總統')`。

9. **★ 資料一定標來源** — 見上方「資料真實性鐵律」第 2 點。任何「補資料」
   「優化排版」「抓關鍵數字」都要記來源 URL／公報檔名／zip 內路徑。

10. **★ 總統縣市／鄉鎮票數曾 4x / 3x 膨脹** — 早期
    `import_presidential_by_county.py` 把 elctks.csv 的所有層級一起加總。
    8 屆中 7 屆受影響，17,216 筆已用官方摘要列覆寫修正（2026-07，
    `fix_presidential_inflation.py` 冪等可重跑）。因為**百分比不受影響**
    所以長期沒被發現 —— 動票數相關 import 時要特別警覺。

11. **2024 以前的總統公報依法沒有政見欄** — 總統副總統選罷法第 44 條
    2023 修法後 2024 才首度刊登政見。2020/2016/2012 總統政見「無公報來源」，
    要收錄只能用政見發表會逐字稿／競選網站存檔，來源等級需另標 —— 屬選項，
    不強做。（已驗證 101 年公報全文無政見欄）

12. **旗艦承諾的任期歸屬要稽核** — 承諾兌現不等於該首長的功勞。落選政見
    不列追蹤；由中央政策實現的要在 `note`／`verification` 揭露；有查核爭議的
    標 `disputed` 並連查核來源（例：柯文哲公宅 42.2% 依事實查核中心判定未達）。

## 關鍵 SQL 查詢 pattern

```sql
-- 1. 個人總票數（去重「全國」+ 縣市重複）
SELECT COALESCE(
    SUM(CASE WHEN er.district='全國' OR er.district LIKE '地區(0%'
             THEN er.votes END),
    SUM(CASE WHEN er.district NOT IN ('全國') AND er.district NOT LIKE '地區(0%'
             THEN er.votes END)
) AS votes
FROM election_results er
WHERE er.candidate_id = ?
GROUP BY er.candidate_id;

-- 2. 各縣市勝出政黨（用 RANK over）
WITH per_county AS (
  SELECT er.district AS county, c.name, p.name AS party, p.color_hex,
         er.votes,
         SUM(er.votes) OVER (PARTITION BY e.election_id, er.district) AS total,
         RANK() OVER (PARTITION BY e.election_id, er.district
                       ORDER BY er.votes DESC) AS rk
  FROM election_results er
  JOIN candidates c ON er.candidate_id=c.candidate_id
  JOIN elections e ON er.election_id=e.election_id
  LEFT JOIN parties p ON c.party_id=p.party_id
  WHERE e.type='presidential' AND er.district != '全國'
    AND COALESCE(c.background, '正總統') != '副總統'
)
SELECT * FROM per_county WHERE rk = 1;
```

## 常用腳本

**完整手冊在 `scripts/README.md`（依 pipeline 順序分類，必讀）。**
`scripts/` 根目錄 = 可重跑的 pipeline；`scripts/archive/`（46 支）= 已跑完的
一次性腳本，保留供查證來源，**不要重跑**（會重複寫入或已被後續修正取代）。

```
pipeline: 下載 → 匯入票數 → 下載公報 → OCR → LLM 分段/潤稿
          → 主題標注 → 抽量化目標 → 稽核 → commit
```

最常用的幾支：
```
audit_authenticity.py            ★ 真實性稽核（commit DB 前必跑）
ocr_llm_segment.py <eid>         ★ 整頁 OCR + LLM 分段（regex 切不開時主力）
ocr_llm_segment_mayoral.py       縣市長版（<eid> <民國年>）
llm_polish_platforms.py          政見潤稿（從 content_raw 重潤）
llm_extract_targets.py           ★ 抽量化承諾（主力管線，extraction_method='llm'）
llm_tag_target_tense.py          tense 標注（past 政績 / future 承諾）
tag_platforms_by_topic.py        政見 → 14 主題
extract_*_bio_safe.py            公報履歷安全抽取（80% 重疊驗證）
track_target_progress.py         旗艦承諾進度抓取（cron 每日跑）
fetch_ly_*.py                    立法院 API（學經歷/提案/質詢/表決）
import_2026_candidates.py        2026 縣市長候選人匯入（登記/正式兩階段）
fix_presidential_inflation.py    總統票數膨脹修正（冪等）
```

## 主要 API endpoint（router prefix 見 `api/main.py`）

```
/elections                 清單、/{id}/results、/townships、/total-votes、/milestones（選舉日曆）
/elections/recalls         2025 大罷免 33 案
/people/{name}             個人頁（含罷免紀錄）
/people/{name}/comparison  ★ 跨屆政見對照（同類型前後兩屆＋主題延續/新增/消失）
/people/{name}/targets     個人量化承諾
/people/{name}/bill-matches 政見 × 立院提案
/platforms/targets/flagship 旗艦承諾追蹤（/tracker 頁用）
/platforms/quantification-stats 全站量化漏斗統計
/platforms/bill-matches/highlights 首頁精選
/topics/{name}/stats|targets
/mayoral/county-winners、/trends/presidential/county-winners（已 normalize 地名）
/issues/fertility          少子化議題缺口分析
```

## Railway 部署

- `git push origin main` 自動觸發
- DB 是檔案直接讀，**每次 deploy 用 commit 過的 db.sqlite**
- 改 DB 的標準收尾：
  ```
  python scripts/audit_authenticity.py && python -m pytest tests/ -q
  sqlite3 data/db.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
  git add data/db.sqlite && git commit && git push
  ```
- `.github/workflows/track-progress.yml` 每日自動抓旗艦承諾進度並開 PR

## 規劃文件

- `docs/roadmap_2026H2.md` — **規劃單一來源**，每輪收尾要更新（含 R1–R4 清債、
  P0–P4 功能、旗艦承諾稽核附錄、政見覆蓋缺口盤點）
- `docs/data_model_v2.md` / `docs/sitemap.md`
- Notion「完整路線圖 v5」https://app.notion.com/p/39149527097a814c9aa6c266584c17b1

## 不要做的事

1. 不要 `git push --force` 到 main
2. 不要 `git add` `.claude/` 或 `data/bulletin_pages_legislators/` 整個資料夾
3. 不要把 votedata.zip 解壓進 git
4. OCR script 啟動後不要刪 PNG cache（中斷會浪費前面工作）
5. **不要憑印象寫任何政見／學經歷／數字** —— 見「資料真實性鐵律」
6. 不要重跑 `scripts/archive/` 裡的一次性腳本
7. 不要在未跑 `audit_authenticity.py` + pytest 的情況下 commit `db.sqlite`
8. 不要讓某條抽取管線刪掉另一條管線的 `platform_targets`
