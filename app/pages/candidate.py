import streamlit as st
import pandas as pd
from services.candidate_service import get_candidates_by_election
from db.queries import get_all_elections


def render():
    st.header("候選人查詢")

    elections_df = get_all_elections()
    if elections_df.empty:
        st.warning("尚無選舉資料")
        return

    elections_df = elections_df.sort_values("date", ascending=False)
    def _label(row):
        base = f"{row['date'][:4]} {row['name']}"
        return f"{base}（{row['description']}）" if row.get("description") else base

    options = {
        _label(row): row["election_id"]
        for _, row in elections_df.iterrows()
    }
    selected_label = st.selectbox("選擇選舉", list(options.keys()))
    election_id = options[selected_label]

    df = get_candidates_by_election(int(election_id))
    if df.empty:
        st.info("此選舉尚無候選人資料")
        return

    has_votes = df["votes"].notna().any() and df["votes"].sum() > 0

    if has_votes:
        elected = df[df["elected"] == 1]
        non_elected = df[df["elected"] != 1]

        st.subheader(f"當選人（{len(elected)} 人）")
        if not elected.empty:
            _render_table(elected, show_votes=True)

        st.subheader(f"落選人（{len(non_elected)} 人）")
        if not non_elected.empty:
            _render_table(non_elected, show_votes=True)
    else:
        st.caption("此選舉尚無得票資料，僅顯示候選人名單")
        _render_table(df, show_votes=False)


def _render_table(df: pd.DataFrame, show_votes: bool):
    cols = ["name", "party_name", "district"]
    rename = {"name": "姓名", "party_name": "政黨", "district": "選區"}

    if show_votes:
        cols.append("votes")
        rename["votes"] = "得票數"

    display = df[cols].rename(columns=rename)

    if show_votes:
        display["得票數"] = display["得票數"].apply(
            lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—"
        )

    st.dataframe(display, use_container_width=True, hide_index=True)
