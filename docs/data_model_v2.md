# 資料模型 v2 設計文件

**版本**：v2 草案　　**日期**：2026-06-12　　**狀態**：草案徵求意見
**Notion**：https://app.notion.com/p/37d49527097a81989452d84fa061499c

## 一、設計目標

從目前的「選舉結果資料庫」升級為「公民政治參與平台」的資料底層，支援：

1. **選舉日曆**：何時要選、選什麼、誰要選
2. **候選人查詢**：政黨、背景、歷屆參選
3. **政見資料庫**：當前政見、歷年政見比對、提案者紀錄
4. **政見追蹤**：兌現狀態、進度更新、來源驗證
5. **公共政策追蹤**：政府政策的執行進度（例：社會住宅）
6. **可信來源**：每一筆資料都有可追溯來源

---

## 二、目前 v1 schema 摘要

5 個表：`elections`、`parties`、`candidates`、`election_results`、`seats`

**主要缺口**：
- `candidates.platform` 是純文字、無來源、無歷年追蹤
- `elections.status` 沒有未來選舉資料
- 沒有「政策」、「兌現追蹤」、「公開資料指標」、「新聞引用」等表
- 沒有「資料來源」追蹤欄位

---

## 三、v2 完整資料模型

### 群組 A：選舉核心（v1 保留 + 強化）

#### A1. elections（強化）

新增：`registration_start`、`registration_end`、`eligible_voters`、`turnout_rate`
status 新值：`scheduled / registration_open / campaigning / completed / cancelled`

#### A2. parties（無變動）

#### A3. candidates（強化）

新增：`birth_year`、`gender`、`photo_url`、`official_website`、`facebook_url`、
`registration_status`、`incumbent`

*移除 `platform` 欄位 → 改用 platforms 表*

#### A4. election_results（強化）

新增：`vote_percentage`、`district_seats`（SNTV 需要）

---

### 群組 B：政見系統（全新）

- **B1. platform_categories** — 政見分類（交通、教育、住宅、能源…）
- **B2. platforms** — 候選人政見項目（含可量化目標）
- **B3. platform_sources** — 政見原始來源（官網、FB、辯論會）
- **B4. platform_history** — 同一人歷年政見比對
- **B5. platform_progress** — 政見兌現進度追蹤

---

### 群組 C：公共政策追蹤（全新）

- **C1. policies** — 政府政策項目
- **C2. policy_milestones** — 政策里程碑
- **C3. policy_data_points** — 定期進度數據

---

### 群組 D：來源與引用（全新）

- **D1. sources** — 統一引用來源
- **D2. source_links** — 多對多關聯到任何實體

---

### 群組 E：使用者與編輯（v2 末期）

- **E1. users**
- **E2. edit_logs**

---

## 四、Schema 遷移策略

| Phase | 內容 |
|---|---|
| 1 | 強化既有表（elections、candidates） |
| 2 | 政見系統表（platforms、platform_sources、platform_history） |
| 3 | 政見進度追蹤（platform_progress） |
| 4 | 公共政策追蹤（policies、milestones、data_points） |
| 5 | 來源與使用者系統 |

---

## 五、待討論問題

1. 政見與政策的邊界
2. 資料正確性如何保證（人工驗證？信度分數？）
3. 政見偏見處理（原文保留？立場標註？）
4. 公共資料時效性（顯示最後更新時間）
5. iOS app 離線需求
6. 法律與隱私（新聞引用、未公開背景資料）

---

詳細欄位定義見 Notion 頁面。
