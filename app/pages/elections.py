import streamlit as st
from services.election_service import get_all_elections

def render():
    st.header("📅 選舉時程")
    df = get_all_elections()
    if df.empty:
        st.info("目前尚無資料，請執行 scripts/import_cec_data.py 匯入資料。")
        return
    status_filter = st.radio("篩選", ["全部", "upcoming", "historical"], horizontal=True)
    if status_filter != "全部":
        df = df[df["status"] == status_filter]
    st.dataframe(df, use_container_width=True)
