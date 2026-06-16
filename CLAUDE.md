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
scripts/              一次性 / 定期執行的資料工具
data/
  db.sqlite           主資料庫（**commit in repo**, Railway 重 deploy 時更新）
  votedata.zip        中選會原始 CSV（**不要 unzip**，腳本動態讀）
  bulletins/          選舉公報 PDF
  bulletin_pages*/    OCR 用渲染 PNG
```

## 資料 schema 重點

- `elections` — 88+ 場（presidential / legislative / mayoral / council）
- `candidates` — 9000+ 人，可同名跨選舉（用 candidate_id 區分）
- `election_results` — 候選人 × 選區 × 票數，含「全國」摘要列
- `township_results` — 總統選舉鄉鎮市區層級（1996–2024）
- `platforms` + `platform_topic_links` + `platform_topics` — 政見全文 + 14 主題標籤
- `platform_targets` — 政見追蹤目標（手動 + auto_extracted）
- `topic_data_sources` — 主題 → 可追蹤的政府開放資料 URL

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
7. **★ 資料一定標來源** — 任何「補資料」「優化排版」「抓關鍵數字」的
   動作都要記錄來源 URL／公報檔名／中選會 zip 內路徑。
   - DB schema：`platforms.source_url`、`candidates.source_url`、
     `platform_targets.source_url`（沒有就加 column）
   - 學經歷補：來源寫進 `candidates.background_source`，前端顯示「資料來源 →」
   - OCR 後的人工潤稿/排版優化要在 `platforms.note` 加 `[人工潤稿 by Claude
     YYYY-MM-DD]`，避免之後分不出來。

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

```
scripts/
  reimport_mayoral_votes.py        修縣市長 4x 膨脹（已跑過）
  reimport_legislative_votes.py    修立委（已跑過）
  reimport_council_votes.py        修議員（已跑過）
  import_presidential_by_county.py 總統縣市層級
  import_presidential_by_township.py 鄉鎮層級
  ocr_bulletin_pages.py            縣市長公報 OCR
  ocr_2024_pdfs.py                 2024 總統/不分區/原住民 OCR
  ocr_2024_regional_legislative.py 2024 區域立委 OCR (73 PDFs)
  tag_platforms_by_topic.py        政見 → 主題自動分類
  extract_platform_targets.py      抽量化承諾
  seed_topic_data_sources.py       主題公開資料 registry
  clean_ocr_noise.py               OCR 雜訊清理
```

## Railway 部署

- `git push origin main` 自動觸發
- DB 是檔案直接讀，**每次 deploy 用 commit 過的 db.sqlite**
- 修 DB 後一定要 `sqlite3 data/db.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"`
  確保 WAL flush，然後 `git add data/db.sqlite && git commit`

## 不要做的事

1. 不要 `git push --force` 到 main
2. 不要 `git add` `.claude/` 或 `data/bulletin_pages_legislators/` 整個資料夾
3. 不要把 votedata.zip 解壓進 git
4. OCR script 啟動後不要刪 PNG cache（中斷會浪費前面工作）
