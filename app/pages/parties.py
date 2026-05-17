import streamlit as st
import pandas as pd
from services.party_service import get_election_cycles_with_results, get_party_results_by_date

TYPE_ZH = {
    "presidential": "總統",
    "legislative":  "立委",
    "mayoral":      "縣市長",
    "council":      "議員",
}


def render():
    st.header("政黨當選結果")

    cycles = get_election_cycles_with_results()
    if cycles.empty:
        st.info("尚無當選資料")
        return

    def cycle_label(row):
        types = "、".join(
            TYPE_ZH.get(t, t) for t in row["types"].split(",")
        )
        return f"{row['date']} （{types}）"

    cycle_options = {cycle_label(row): row["date"] for _, row in cycles.iterrows()}
    selected_label = st.selectbox("選擇選舉週期", list(cycle_options.keys()))
    selected_date = cycle_options[selected_label]

    df = get_party_results_by_date(selected_date)
    if df.empty:
        st.info("此週期無當選資料")
        return

    # 依選舉類型分組顯示
    for etype in df["election_type"].unique():
        sub = df[df["election_type"] == etype].copy()
        desc = sub["description"].dropna().unique()
        section = TYPE_ZH.get(etype, etype)
        if len(desc):
            section += f"（{'、'.join(desc)}）"

        st.subheader(section)

        total = sub["elected_count"].sum()
        sub = sub[["party_name", "elected_count"]].rename(
            columns={"party_name": "政黨", "elected_count": "當選人數"}
        )
        sub["佔比"] = (sub["當選人數"] / total * 100).map("{:.1f}%".format)

        st.dataframe(sub, use_container_width=True, hide_index=True)
        st.caption(f"合計 {total} 席")
