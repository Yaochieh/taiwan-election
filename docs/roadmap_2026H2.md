# 正至 · 2026 H2 重整與功能規劃

**日期**：2026-07-05　　**狀態**：進行中
**主軸**：政見量化與追蹤（把「政見清單」升級成「兌現追蹤平台」）

---

## 一、體檢摘要（2026-07-05）

### 資產

| 資產 | 規模 |
|---|---|
| 選舉 / 候選人 / 票數列 | 90 場 / 9,045 人 / 90 萬+ 列（含鄉鎮 18,418）|
| 政見全文 | 860 條（立委 513、縣市長 217、總統 6 組）|
| 量化承諾 `platform_targets` | 1,414 筆（LLM 抽取）|
| 主題系統 | 15 主題、3,380 個政見連結、`topic_data_sources` 19 筆 |
| Pipeline | OCR→LLM 潤稿→主題→抽取→稽核（見 `scripts/README.md`）|

### 問題

1. **🔴 追蹤鏈斷鏈**：`platforms → targets(1414) → progress(0 筆) → 開放資料`。
   `platform_target_progress` 是空的——有承諾、有資料源 registry，但沒有任何進度記錄。
2. **🔴 已修（50b9ff4）**：`extract_platform_targets.py` 全量重抽曾誤刪 1,414 筆
   LLM targets → 已還原，並加 `extraction_method`(llm/regex) 欄位隔離兩管線。
3. **🟡 孤兒資料**：`platform_progress_sources` 21 筆指向空的 progress 表。
4. **🟡 targets 品質**：`status` 全部 `in_progress`（欄位未啟用）、
   `baseline_value` / `target_date` 幾乎全空 → 進度條畫不出來。
5. **🟡 覆蓋缺口**：議員 4,924 人政見 0 筆；總統政見僅 2024；2020 前立委無政見。
6. **⚪ 死表**：`platform_categories`、`seats` 空表。

---

## 二、重整計畫（R，清債）

| # | 事項 | 做法 | 狀態 |
|---|---|---|---|
| R1 | targets 補骨架 | `backfill_target_dates.py` 補 41 筆 target_date；旗艦承諾 baseline 歸屬修正（社宅/再生能源設基準、租補低標揭露）| ✅ 2026-07-05 |
| R2 | 清孤兒 | 已刪 21 筆孤兒，救回 2 個 gov API URL 進 registry | ✅ 2026-07-05 |
| R3 | 管線合流 | regex 版已定位為稽核/dry-run 工具（docstring 註明），正式抽取用 LLM 管線（原生懂中文數字）；`extraction_method` 隔離兩管線 | ✅ 2026-07-05 |
| R4 | 死表處置 | 調查後**保留**：`seats` 被 `/parties/seats` endpoint 引用、`platform_categories` 被 import_platforms.py 引用，刪除風險大於價值 | ✅ 2026-07-05（決策：不刪）|

**P0 已完成（2026-07-05）**：追蹤鏈接通——12 條旗艦承諾有進度記錄（藍5綠6柯1，
全數人工查證附來源、多來源官方/媒體交叉），首頁「說到，做到了嗎？」開票式看板
+ /tracker 完整頁（含全站量化統計漏斗）上線，`track-progress.yml` 每日自動抓取開 PR。

**P2 已完成（2026-07-05）**：政見×立院提案對照上線（65位/1,118筆，57條透明
關鍵詞規則），含「零相關提案」標注（199條）；個人頁與首頁精選帶。

**真實性稽核（2026-07-05）**：12條旗艦逐條任期歸屬稽核。柯文哲公宅依
事實查核中心改判 42.2% 終局未達（標 disputed）；/tracker 顯示歸屬註記、
首頁達標項有 caveat 加 ⚠、爭議項標「⚠ 查核有爭議」連查核來源。

**P1 準備（2026-07-05）**：`import_2026_candidates.py` 就緒（登記/正式兩階段、
退選偵測、強制標來源）。時程：8/31-9/4 登記、11/12+11/17 正式名單、11月中公報OCR。

---

## 三、功能擴充（P，量化＋追蹤為主軸）

### P0 · 政見追蹤 MVP —— 把斷鏈接起來（最高價值）

- 選 30–50 個**旗艦承諾**：現任者 + 有數字 + 對得上開放資料
  （社宅戶數、長照涵蓋率、護病比、托育名額…）
- `scripts/track_target_progress.py`：從 `topic_data_sources` 抓當前值
  → 寫 `platform_target_progress`（含 `source_url`、`retrieved_at`，資料一定標來源）
- 前端 target 詳情頁：進度條 baseline → current → target + 歷次記錄時間軸 + 來源連結
- 首長記分卡從「承諾數」升級為「兌現率」

### P1 · 🔥 2026 縣市長選舉（時效性最高，2026-11 投票）

- 現在 7 月，候選人登記約 9 月、公報約 11 月中
- 平台第一次能「選前收政見 → 選後全程追蹤」的完整週期
- 選舉日曆頁（`elections.status='scheduled'`，v2 設計已有）
- 公報一出立即 OCR（pipeline 現成）

### P2 · 驗證管線標準化

- `verification_status` 現況：in_office 66 / not_executed 1056 / self_claim 45 / pending 247
- 建立明確狀態機 + 人工抽查介面
- 立法院資料（`fetch_ly_*`：提案/質詢/表決）→「立委政見 vs 實際提案」對照

### P3 · 量化抽取強化

- 分數（三分之一→0.33）、倍數（翻倍/減半）、「N 次/場/名額」單位
- 反向標注「不可量化」政見（大幅提升、積極推動）——前端明示「此承諾無法客觀檢驗」

### P4 · 自動化

- cron 每月跑 progress 抓取 + 變化偵測，DB commit 即部署

---

## 四、執行順序

**R2（清債）→ P0 打樣（10 個旗艦承諾跑通第一條 progress）→ R1 → P1（8 月前完成選舉日曆）→ P2 → P3/P4**

---

## 附：管線安全守則（2026-07-05 事故教訓）

- `platform_targets` 有兩條抽取管線：`llm_extract_targets.py`（主力）與
  `extract_platform_targets.py`（regex，稽核用）。**各管線只能刪
  `extraction_method` 是自己的 rows**，絕不可無條件 `DELETE auto_extracted=1`。
- 改 DB 前先確認：`git show HEAD:data/db.sqlite` 可隨時還原上一版。
