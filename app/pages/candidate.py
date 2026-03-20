import streamlit as st
from services.candidate_service import get_candidates_by_election

def render():
    st.header("👤 候選人查詢")
    election_id = st.number_input("輸入選舉 ID", min_value=1, step=1)
    if st.button("查詢"):
        df = get_candidates_by_election(int(election_id))
        if df.empty:
            st.warning("查無資料")
        else:
            st.dataframe(df, use_container_width=True)
