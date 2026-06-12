import math
import streamlit as st
import pandas as pd
from services.party_service import (
    get_election_cycles_with_results,
    get_party_results_by_date,
    get_party_list_votes_by_date,
)

TYPE_ZH = {
    "presidential": "總統",
    "legislative":  "立委",
    "mayoral":      "縣市長",
    "council":      "議員",
}

# 2008 起 34 席，之前 41 席
_SEATS_NEW = 34
_SEATS_OLD = 41
_THRESHOLD = 0.05


def _compute_seats(votes_series: pd.Series, date: str) -> pd.Series:
    """依 Hare quota + 最大餘數法計算不分區席次"""
    total_seats = _SEATS_NEW if date >= "2008-01-01" else _SEATS_OLD
    total_votes = votes_series.sum()
    threshold = total_votes * _THRESHOLD

    qualifying = votes_series[votes_series >= threshold]
    if qualifying.empty:
        return pd.Series(0, index=votes_series.index)

    q_total = qualifying.sum()
    quota = q_total / total_seats

    exact = qualifying / quota
    base = exact.apply(math.floor)
    remainder = exact - base

    remaining = total_seats - base.sum()
    top_remainder = remainder.nlargest(remaining).index
    base[top_remainder] += 1

    return base.reindex(votes_series.index, fill_value=0)


def render():
    st.header("政黨當選結果")

    cycles = get_election_cycles_with_results()
    if cycles.empty:
        st.info("尚無當選資料")
        return

    def cycle_label(row):
        types = "、".join(TYPE_ZH.get(t, t) for t in row["types"].split(","))
        return f"{row['date']} （{types}）"

    cycle_options = {cycle_label(row): row["date"] for _, row in cycles.iterrows()}
    selected_label = st.selectbox("選擇選舉週期", list(cycle_options.keys()))
    selected_date = cycle_options[selected_label]

    df = get_party_results_by_date(selected_date)
    if df.empty:
        st.info("此週期無當選資料")
        return

    # 各選舉類型席次分組
    for etype in df["election_type"].unique():
        sub = df[df["election_type"] == etype].copy()
        desc = sub["description"].dropna().unique()
        section = TYPE_ZH.get(etype, etype)
        if len(desc):
            section += f"（{'、'.join(desc)}）"

        st.subheader(section)

        total = sub["elected_count"].sum()
        sub_display = sub[["party_name", "elected_count"]].rename(
            columns={"party_name": "政黨", "elected_count": "當選人數"}
        ).copy()
        sub_display["佔比"] = (sub_display["當選人數"] / total * 100).map("{:.1f}%".format)

        st.bar_chart(sub_display.set_index("政黨")["當選人數"])
        st.dataframe(sub_display, use_container_width=True, hide_index=True)
        st.caption(f"合計 {total} 席")

    # 立委不分區政黨票（若有）
    plist = get_party_list_votes_by_date(selected_date)
    if not plist.empty:
        st.subheader("不分區立委：政黨票與席次分配")

        vote_series = plist.set_index("party_name")["votes"]
        seat_series = _compute_seats(vote_series, selected_date)

        total_votes = vote_series.sum()

        plist_display = pd.DataFrame({
            "政黨": plist["party_name"].values,
            "得票數": plist["votes"].apply(lambda v: f"{int(v):,}").values,
            "得票率": (plist["votes"] / total_votes * 100).map("{:.2f}%".format).values,
            "分配席次": plist["party_name"].map(seat_series).fillna(0).astype(int).values,
            "達門檻": plist["elected"].apply(lambda e: "✓" if e else "").values,
        })

        st.bar_chart(vote_series)
        st.dataframe(plist_display, use_container_width=True, hide_index=True)
        threshold = int(total_votes * _THRESHOLD)
        total_seats = _SEATS_NEW if selected_date >= "2008-01-01" else _SEATS_OLD
        st.caption(
            f"政黨票總數：{int(total_votes):,}　　"
            f"5% 門檻：{threshold:,} 票　　"
            f"不分區總席次：{total_seats} 席"
        )
