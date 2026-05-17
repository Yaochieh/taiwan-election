# 正至平台 — 網站地圖與架構說明

## 一、Streamlit 應用頁面

| 頁面名稱 | 路徑 | 功能說明 |
|----------|------|----------|
| 選舉時程 | `app/pages/elections.py` | 顯示所有選舉的時間、類型、狀態清單 |
| 政黨席次 | `app/pages/parties.py` | 依選舉週期顯示各政黨席次及得票率 |
| 候選人查詢 | `app/pages/candidate.py` | Tab 1：依選舉查詢候選人名單與得票；Tab 2：跨選舉搜尋候選人歷史紀錄 |
| 縣市長歷屆結果 | `app/pages/mayors.py` | 矩陣式顯示各縣市歷屆縣市長當選人（含政黨色彩標示）；加上歷年席次堆疊長條圖 |
| 趨勢分析 | `app/pages/trends.py` | 總統選舉與不分區政黨票歷年趨勢折線圖 |

---

## 二、FastAPI 端點

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/elections` | 所有選舉清單 |
| GET | `/elections/{id}` | 單筆選舉詳情 |
| GET | `/candidates/{election_id}` | 某選舉的候選人清單 |
| GET | `/candidates/detail/{candidate_id}` | 單一候選人詳情 |
| GET | `/parties` | 所有政黨清單 |
| GET | `/parties/{party_id}/seats` | 某政黨的席次資料 |

---

## 三、資料庫綱要（SQLite）

### elections
| 欄位 | 型別 | 說明 |
|------|------|------|
| election_id | INTEGER PK | |
| name | TEXT | 選舉名稱 |
| type | TEXT | presidential / legislative / mayoral |
| date | DATE | 投票日 |
| status | TEXT | upcoming / historical |
| description | TEXT | 子類型（例如：不分區政黨） |
| theme_id | TEXT UNIQUE | CEC 主題識別碼 |

### parties
| 欄位 | 型別 | 說明 |
|------|------|------|
| party_id | INTEGER PK | |
| name | TEXT | 政黨全名 |
| abbreviation | TEXT | 縮寫 |
| color_hex | TEXT | 顯示顏色 |

### candidates
| 欄位 | 型別 | 說明 |
|------|------|------|
| candidate_id | INTEGER PK | |
| name | TEXT | 姓名 |
| party_id | INTEGER FK | |
| election_id | INTEGER FK | |
| district | TEXT | 選區（地區代碼或地名） |
| background | TEXT | 背景資料 |
| platform | TEXT | 政見 |

### election_results
| 欄位 | 型別 | 說明 |
|------|------|------|
| result_id | INTEGER PK | |
| election_id | INTEGER FK | |
| candidate_id | INTEGER FK | |
| district | TEXT | 選區 |
| votes | INTEGER | 得票數 |
| elected | BOOLEAN | 是否當選 |

### seats
| 欄位 | 型別 | 說明 |
|------|------|------|
| seat_id | INTEGER PK | |
| election_id | INTEGER FK | |
| party_id | INTEGER FK | |
| level | TEXT | 席次類型（district / party_list） |
| count | INTEGER | 席次數 |

---

## 四、未來改善方向

### 優先級 P0（核心功能補強）
- [ ] 補齊 2005、2009、2017 縣市長資料缺口
- [ ] 縣市長歷史矩陣加入 tooltip 顯示詳細得票數
- [ ] 選舉結果地圖視覺化（台灣 GeoJSON + choropleth）

### 優先級 P1（使用體驗）
- [ ] 候選人個人頁面（顯示歷次參選記錄、政黨變化）
- [ ] 比較模式：選取兩位候選人比對各選區得票
- [ ] 選舉結果 permalink（可分享特定選舉/候選人的 URL）

### 優先級 P2（資料擴充）
- [ ] 立法委員選區資料（各選區得票率地圖）
- [ ] 政黨歷史沿革（合併、解散、改名記錄）
- [ ] 議員選舉（直轄市議員、縣市議員）

### 優先級 P3（平台強化）
- [ ] 資料更新排程（CEC API 定期同步）
- [ ] 多語言支援（英文版）
- [ ] 開放 API 供第三方使用
- [ ] 選舉新聞彙整（媒體連結）
