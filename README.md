# 正至 — 台灣選舉資訊平台

> 希望台灣政治正在往好的路上走。

把台灣的選舉資料整合在一起：誰選上、當初說了什麼、後來做到了沒。

**線上**：[taiwan-election-web.vercel.app](https://taiwan-election-web.vercel.app)
**前端 repo**：[Yaochieh/taiwan-election-web](https://github.com/Yaochieh/taiwan-election-web)（Next.js）
**本 repo**：API 後端與資料處理管線（Python / FastAPI / SQLite）

---

## 資料原則：寧可留白，不補寫

開發過程中曾發生 AI 用自身知識「腦補」政見內容的事故 —— 看起來煞有其事，但公報上根本沒這回事。所有無法對照原檔的資料已全部刪除重建，並建立了防止再犯的機制：

| 機制 | 做法 |
|---|---|
| 只用原始來源 | 政見一律從選舉公報原檔抽取，查不到就留白 |
| 保留原文可對照 | 每條政見存 `content_raw`（原始 OCR），整理後版本須與原文 4-gram 重疊 ≥ 80% 才採用 |
| 一切標來源 | `platforms.source_url`、`candidates.background_source`、`platform_progress_sources` 逐筆記錄出處與擷取日期 |
| 自動稽核擋關 | `scripts/audit_authenticity.py` 五項檢查 + 42 項測試，CI 未過不予發布 |

```bash
python scripts/audit_authenticity.py   # commit data/db.sqlite 前必跑
python -m pytest tests/ -q
```

---

## 資料覆蓋

| 項目 | 數量 |
|---|---|
| 選舉 | 91 場（80 場已舉行，1994 年起） |
| 候選人 | 9,045 位 |
| 得票紀錄 | 9,077 筆（縣市／選區層級） |
| 鄉鎮市區得票 | 18,418 筆（總統 1996–2024） |
| 政見全文 | 883 條 |
| 量化承諾 | 1,692 筆 |
| 旗艦承諾追蹤 | 20 條（附官方統計來源） |
| 罷免案 | 33 案（2025 大罷免） |
| 政黨 | 410 個（含歷史小黨） |

### 政見覆蓋率（目前最大的缺口）

| 選舉類型 | 候選人 | 有政見 | 覆蓋率 |
|---|---:|---:|---:|
| 縣市長 | 620 | 240 | 38.7% |
| 立法委員 | 3,451 | 513 | 14.9% |
| 總統／副總統 | 50 | 6 | 12.0% |
| 縣市議員 | 4,924 | 0 | 0% |

> 總統偏低是法規造成的：2024 年以前的總統副總統選舉公報，依選罷法第 44 條僅刊登個人資料、不含政見，2023 年修法後 2024 年才首度刊登。

---

## 快速啟動

```bash
pip install -r requirements.txt          # 部署用最小依賴（4 個套件）
uvicorn api.main:app --reload --port 8000
sqlite3 data/db.sqlite                   # 直接看資料
```

資料工程／Streamlit 需要額外套件：

```bash
pip install -r requirements-dev.txt
streamlit run app/main.py                # 早期 MVP UI，主力已是 Next.js 前端
```

`data/db.sqlite` 隨 repo 附上，可直接啟動，無需匯入。

> 對外部署的 API 已關閉 `/docs`、`/redoc`、`/openapi.json`；本機開發若需要 Swagger UI，把 `api/main.py` 裡的三個 `None` 拿掉即可。

---

## 資料處理管線

```
下載 → 匯入票數 → 下載公報 → OCR → LLM 分段/潤稿
     → 主題標注 → 抽量化承諾 → 稽核 → commit
```

完整腳本說明見 **[`scripts/README.md`](scripts/README.md)**。
`scripts/` 根目錄是可重跑的管線，`scripts/archive/` 是已跑完的一次性腳本（保留供查證，不要重跑）。

常用：

| 腳本 | 用途 |
|---|---|
| `audit_authenticity.py` | 真實性稽核（commit DB 前必跑） |
| `ocr_llm_segment.py` | 整頁 OCR + LLM 分段 |
| `llm_extract_targets.py` | 抽量化承諾（主力管線） |
| `track_target_progress.py` | 旗艦承諾進度抓取（每日 cron） |
| `fetch_ly_*.py` | 立法院開放資料（學經歷／提案／質詢／表決） |
| `import_2026_candidates.py` | 2026 縣市長候選人匯入 |

---

## 資料庫 Schema

**選舉核心**

| 表格 | 說明 |
|---|---|
| `elections` | 選舉基本資料（名稱、日期、類型、狀態） |
| `candidates` | 候選人（姓名、黨籍、選區、學經歷及其來源） |
| `election_results` | 各選區得票與當選旗標 |
| `township_results` | 總統選舉鄉鎮市區層級得票 |
| `recall_results` | 罷免案結果（審定票數、同意門檻） |
| `election_milestones` | 選舉法定時程 |
| `parties` / `seats` | 政黨與選後席次 |

**政見與兌現追蹤**

```
platforms → platform_targets → platform_target_progress → topic_data_sources
  ↑OCR/LLM      ↑量化承諾            ↑實際進度值             ↑政府開放資料
```

| 表格 | 說明 |
|---|---|
| `platforms` | 政見全文，含 `content_raw` 原始 OCR |
| `platform_topics` / `platform_topic_links` | 15 個主題標籤 |
| `platform_targets` | 量化承諾（`extraction_method` 隔離 llm／regex 兩管線、`tense` 區分政績與承諾、`is_flagship`） |
| `platform_target_progress` | 旗艦承諾的實際進度值 |
| `platform_progress_sources` | 進度的來源網址與擷取日期 |
| `platform_bill_matches` | 立委政見 × 立院提案對照 |
| `topic_data_sources` | 主題 → 可追蹤的政府開放資料 |

### 選舉類型

`presidential`（總統副總統）／`legislative`（立委：區域、原住民、不分區）／`mayoral`（縣市長）／`council`（縣市議員）

---

## 已知限制

- **OCR 會有錯字**。公報多為掃描影像，密集排版的多欄版面尤其容易出錯。
- **主題分類是關鍵字比對**，政見出現「社宅」就歸到住宅主題，不代表候選人真的著墨。
- **量化承諾由 LLM 抽取**，可能漏抽、誤判單位或期限。
- **兌現追蹤只有 20 條**，是逐條人工查證的示範，不是全面盤點；沒被追蹤不代表沒兌現。
- **承諾的功勞歸屬複雜**：有些由中央政策達成、有些跨越多任期、有些查核單位有爭議 —— 這些都在資料裡標註說明。

---

## 專案結構

```
api/            FastAPI 入口與各功能 router
db/queries.py   所有 SQL 查詢
models/         Pydantic 回應模型
scripts/        可重跑的資料管線（archive/ 為一次性腳本）
tests/          資料不變量 + API smoke（42 項）
docs/           路線圖、資料模型、網站地圖
app/            早期 Streamlit MVP（保留）
data/
  db.sqlite       主資料庫（commit 在 repo，部署直接讀）
  votedata.zip    中選會原始 CSV（不解壓，腳本動態讀）
  bulletins/      選舉公報 PDF
.github/workflows/
  ci.yml            稽核 + 測試
  track-progress.yml 每日抓進度開 PR
  keepalive.yml     免費層保活
```

---

## 部署

後端 Render（免費層，`render.yaml`）、前端 Vercel。push 到 `main` 自動部署。

改資料庫的標準收尾：

```bash
python scripts/audit_authenticity.py && python -m pytest tests/ -q
sqlite3 data/db.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
git add data/db.sqlite && git commit && git push
```

---

## 貢獻

歡迎回報資料錯誤、提供建議或送 PR。最有幫助的是：

1. **資料錯誤** —— 開 issue 附上頁面連結與正確資料的出處
2. **政見補完** —— 尤其議員（4,924 位，公報多為影像版需 OCR）
3. **開放資料來源** —— `topic_data_sources` 只有 20 條，主題頁的「達標對照」大多還接不到數據

送 PR 前請確認 `python scripts/audit_authenticity.py` 與 `pytest tests/ -q` 都通過。

授權：MIT。資料引自中央選舉委員會公開資料，引用請註明來源並連結回本專案。
