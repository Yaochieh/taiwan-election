import streamlit as st
import pandas as pd
from services.candidate_service import get_candidates_by_election
from db.queries import get_all_elections, get_total_votes_by_election
from app.utils import clean_district


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
    total_votes = get_total_votes_by_election(int(election_id)) if has_votes else 0

    if has_votes:
        elected = df[df["elected"] == 1]
        non_elected = df[df["elected"] != 1]

        st.subheader(f"當選人（{len(elected)} 人）")
        if not elected.empty:
            _render_table(elected, show_votes=True, total_votes=total_votes)

        st.subheader(f"落選人（{len(non_elected)} 人）")
        if not non_elected.empty:
            _render_table(non_elected, show_votes=True, total_votes=total_votes)
    else:
        st.caption("此選舉尚無得票資料，僅顯示候選人名單")
        _render_table(df, show_votes=False, total_votes=0)


def _render_table(df: pd.DataFrame, show_votes: bool, total_votes: int):
    display = pd.DataFrame({
        "姓名": df["name"].values,
        "政黨": df["party_name"].values,
        "選區": df["district"].apply(clean_district).values,
    })

    if show_votes:
        display["得票數"] = df["votes"].apply(
            lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—"
        ).values
        if total_votes > 0:
            display["得票率"] = df["votes"].apply(
                lambda v: f"{v / total_votes * 100:.2f}%" if pd.notna(v) and v > 0 else "—"
            ).values

    st.dataframe(display, use_container_width=True, hide_index=True)
