import streamlit as st
from services.party_service import get_all_parties

def render():
    st.header("🏛️ 政黨席次")
    df = get_all_parties()
    if df.empty:
        st.info("目前尚無資料。")
        return
    st.dataframe(df, use_container_width=True)
