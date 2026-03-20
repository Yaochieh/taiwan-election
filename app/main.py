import streamlit as st
from db.queries import init_db

st.set_page_config(page_title="正至 — 台灣選舉資訊", layout="wide")

# 確保 DB 存在
init_db()

st.title("🗳️ 正至：台灣選舉資訊平台")
st.caption("希望台灣政治正在往好的路上走")

page = st.sidebar.selectbox(
    "選擇頁面",
    ["選舉時程", "政黨席次", "候選人查詢"]
)

if page == "選舉時程":
    from app.pages.elections import render
    render()
elif page == "政黨席次":
    from app.pages.parties import render
    render()
elif page == "候選人查詢":
    from app.pages.candidate import render
    render()
