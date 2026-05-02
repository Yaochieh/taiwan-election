# 正至 — 台灣選舉資訊平台

希望台灣政治正在往好的路上走。

## 技術架構
- MVP UI: Streamlit
- 後端 API: FastAPI
- 資料庫: SQLite → PostgreSQL
- 資料來源: 中選會開放資料

## 快速開始

```bash
pip install -r requirements.txt
```

### Streamlit UI
```bash
streamlit run app/main.py
```

### FastAPI 後端
```bash
uvicorn api.main:app --reload
# Swagger UI: http://localhost:8000/docs
```

## 資料匯入流程

```bash
# 1. 建立選舉索引（從中選會 API）
python scripts/build_elections_index.py

# 2. 下載選舉 Excel ZIP
python scripts/download_excel.py --subject P0      # 總統
python scripts/download_excel.py --subject L0      # 立委
python scripts/download_excel.py --subject C2      # 縣市長
python scripts/download_excel.py --subject T1      # 縣市議員

# 3. 匯入到 SQLite
python scripts/parse_and_import.py

# 4. 植入政黨資料
python scripts/seed_parties.py
```

## 資料庫 Schema

| 表格 | 說明 |
|------|------|
| `elections` | 選舉基本資料（名稱、日期、類型） |
| `parties` | 政黨（名稱、縮寫、代表色） |
| `candidates` | 候選人（姓名、黨籍、選區） |
| `election_results` | 各選區得票明細 |
| `seats` | 選後席次（政黨 x 選舉） |
