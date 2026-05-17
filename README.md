# 正至 — 台灣選舉資訊平台

希望台灣政治正在往好的路上走。

## 技術架構

| 層級 | 技術 |
|------|------|
| MVP UI | Streamlit |
| 後端 API | FastAPI |
| 資料庫 | SQLite（未來遷移 PostgreSQL） |
| 資料來源 | 中選會開放資料（db.cec.gov.tw） |

---

## 快速啟動

### 安裝套件

```bash
pip install -r requirements.txt
```

### Streamlit UI（前端）

```bash
streamlit run app/main.py
```

瀏覽器開啟 http://localhost:8501

### FastAPI 後端

```bash
uvicorn api.main:app --reload
```

Swagger UI：http://localhost:8000/docs

---

## 資料匯入流程

資料庫檔案 `data/db.sqlite` 已隨專案附上，可直接啟動。若需重建：

```bash
# 1. 建立選舉索引（從中選會 API）
python scripts/build_elections_index.py

# 2. 匯入選舉資料（從 data/votedata.zip）
python scripts/import_votedata.py

# 3. 植入政黨基本資料
python scripts/seed_parties.py

# 4. 連結候選人與政黨
python scripts/link_candidate_parties.py

# 5. 計算不分區政黨當選席次
python scripts/compute_party_list_seats.py
```

---

## 資料庫 Schema

| 表格 | 說明 |
|------|------|
| `elections` | 選舉基本資料（名稱、日期、類型） |
| `parties` | 政黨（名稱、縮寫、代表色） |
| `candidates` | 候選人（姓名、黨籍、選區） |
| `election_results` | 各選區得票數與當選旗標 |
| `seats` | 選後席次（政黨 × 選舉） |

### 支援的選舉類型

| `type` | 說明 |
|--------|------|
| `presidential` | 總統副總統選舉 |
| `legislative` | 立法委員選舉（區域、原住民、不分區） |
| `mayoral` | 縣市長選舉 |
| `council` | 縣市議員選舉 |

---

## 資料覆蓋範圍

- 時間：1994 年 — 2024 年
- 選舉總場數：76 場
- 候選人總數：8,983 人
- 得票記錄：2,714 筆（總統、縣市長、立委完整覆蓋）
- 當選旗標：354 筆

> 議員選舉（SNTV 複數選區）因結構複雜，當選旗標暫未計算。

---

## 專案結構

```
taiwan-election/
├── api/            FastAPI 後端
│   └── routers/    elections / candidates / parties
├── app/            Streamlit UI
│   └── pages/      elections / candidate / parties
├── data/           資料庫與原始資料
│   ├── db.sqlite
│   └── votedata.zip
├── db/             SQL 查詢層
├── models/         Pydantic 資料模型
├── scripts/        資料匯入腳本
├── services/       業務邏輯層
└── requirements.txt
```
