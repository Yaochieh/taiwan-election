# scripts/ 手冊

`scripts/` 根目錄 = 可重跑的 pipeline 與工具；`scripts/archive/` = 已跑完的一次性腳本（保留供查證 git 歷史與資料來源，**不要重跑** —— 大多會重複寫入或已被後續修正取代）。

## Pipeline 總覽（依執行順序）

```
下載 → 匯入票數 → 下載公報 → OCR → LLM 分段/潤稿 → 主題標注 → 抽量化目標 → 稽核 → commit
```

### 1. 選舉資料下載 / 匯入
| 腳本 | 用途 |
|---|---|
| `build_elections_index.py` | 從中選會 API 建 `data/elections_index.json` |
| `download_excel.py` | 下載各選舉 ZIP 到 `data/downloads/` |
| `import_votedata.py` | 主匯入：votedata.zip → elections/candidates/election_results |
| `import_presidential_by_county.py` / `_by_township.py` | 總統縣市/鄉鎮層級（⚠️ 歷史 bug：曾把 elctks.csv 全層級加總造成 4x/3x 膨脹） |
| `fix_presidential_inflation.py` | 用官方摘要列覆寫總統縣市/鄉鎮票數（2026-07 修正，冪等可重跑） |
| `compute_party_list_seats.py` | 不分區席次（Hare quota + 最大餘數）|
| `seed_parties.py` / `link_candidate_parties.py` | 政黨種子與連結 |

### 2. 公報下載 / OCR
| 腳本 | 用途 |
|---|---|
| `download_bulletins.py` / `download_bulletin_office.py` / `download_legislative_pdfs.py` | 公報 PDF |
| `ocr_2024_single_district_legislative.py` | ★ 共用底層（`render_pages`/`ocr_image`/`JOBS`），多支腳本 import 它 |
| `ocr_2024_regional_legislative.py` / `ocr_2024_pdfs.py` | 2024 區域立委 / 總統+不分區 |
| `ocr_mayoral_by_year.py` / `ocr_legislative_by_year.py` | 依年份縣市長 / 立委（`county_from_filename` 被 import）|
| `ocr_llm_segment.py <eid>` | ★ 整頁 OCR + LLM 分段（regex 切不開時的主力）|
| `ocr_llm_segment_mayoral.py <eid> <民國年>` | 縣市長版 |
| `ocr_highdpi_county.py` / `ocr_highdpi_mayoral_batch.py` / `ocr_partylist_fulldpi.py` | 300 DPI 救援（版面太密 200 DPI 抽不到）|
| `ocr_bulletin_pages.py` | 縣市長公報整頁 OCR |
| `extract_bulletin_images.py` / `extract_candidate_photos.py` | 圖片政見 / 大頭照抽取 |
| `parse_bulletin.py` / `parse_bulletin_v2.py` / `import_platforms.py` / `import_legislative_platforms.py` | 早期 parser（部分仍被 import）|

### 3. LLM 加工（都有防腦補措施）
| 腳本 | 用途 |
|---|---|
| `llm_polish_platforms.py` / `llm_repolish_from_raw.py` | 潤稿（從 content_raw 重潤）|
| `llm_extract_targets.py` / `extract_platform_targets.py` | 抽量化承諾 |
| `llm_tag_target_tense.py` | tense 標注（past 政績 / future 承諾）|
| `llm_merge_dedupe.py` | targets 去重 |
| `tag_platforms_by_topic.py` | 政見 → 14 主題 |
| `clean_ocr_noise.py` / `clean_json_contaminated.py` | OCR 雜訊 / LLM 回傳 JSON 污染清理 |
| `extract_president_bio_safe.py` / `extract_mayoral_bio_safe.py` | ★ 公報履歷安全抽取：80% 4-gram 重疊驗證，不過就拒絕（縣市長版 14/14 全拒 = 機制正常）|

### 4. 外部公開資料
| 腳本 | 用途 |
|---|---|
| `fetch_ly_legislators.py` / `fetch_ly_activity.py` / `fetch_ly_votes.py` | 立法院 ly.govapi.tw（學經歷/提案/質詢/表決）|
| `fetch_births.py` | 內政部出生數（少子化議題）|
| `fetch_wiki_background.py` | 維基百科簡介（標注來源為維基）|
| `sync_open_data.py` | 政見追蹤開放資料同步（社宅/長照/都更）|
| `seed_topic_data_sources.py` | 主題 → 政府開放資料 registry |

### 5. 稽核（commit DB 前必跑）
```
python scripts/audit_authenticity.py            # 5 項檢查，exit 1 = 有新問題
python scripts/audit_authenticity.py --update-baseline   # 修完舊帳後更新基準
python -m pytest tests/ -q                      # 資料不變量 + API smoke
```

## 防腦補鐵律（本專案最高原則）
1. 任何政見/履歷文字必須來自真實公報 OCR（`content_raw` 100% 保留）
2. LLM 只能「重排原文的字」— 輸出對原文 4-gram 重疊 < 80% 一律拒絕
3. 寧可從缺，不可編造；來源一律標注（platform_sources / background_source / note）
4. `content_raw IS NULL` 或「同選舉多人政見開頭相同」= 稽核紅燈
