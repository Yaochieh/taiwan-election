import streamlit as st
import pandas as pd
from db.queries import get_presidential_vote_trend, get_party_list_vote_trend

_MAIN_PARTIES = {"民主進步黨", "中國國民黨", "台灣民眾黨", "親民黨", "新黨", "時代力量"}


def render():
    st.header("選舉趨勢分析")

    tab1, tab2 = st.tabs(["總統選舉", "立委不分區政黨票"])

    with tab1:
        _render_presidential()

    with tab2:
        _render_party_list()


def _render_presidential():
    st.subheader("歷屆總統選舉得票率")
    df = get_presidential_vote_trend()
    if df.empty:
        st.info("無資料")
        return

    # 計算各年度總票數與得票率
    totals = df.groupby("date")["votes"].sum().rename("total")
    df = df.join(totals, on="date")
    df["得票率"] = df["votes"] / df["total"] * 100

    # 取主要政黨（DPP / KMT）趨勢
    major = df[df["party_name"].isin({"民主進步黨", "中國國民黨"})].copy()
    pivot = major.pivot_table(index="date", columns="party_name", values="得票率")
    pivot.index = pivot.index.str[:4]  # 只顯示年份
    pivot.columns.name = None

    st.line_chart(pivot)
    st.caption("民主進步黨 vs 中國國民黨 各屆得票率（%）")

    # 完整資料表
    with st.expander("查看各屆完整得票資料"):
        display = df[["date", "candidate_name", "party_name", "votes", "得票率"]].copy()
        display["date"] = display["date"].str[:4]
        display["votes"] = display["votes"].apply(lambda v: f"{int(v):,}")
        display["得票率"] = display["得票率"].map("{:.2f}%".format)
        display = display.rename(columns={
            "date": "年份", "candidate_name": "候選人",
            "party_name": "政黨", "votes": "得票數"
        })
        st.dataframe(display, use_container_width=True, hide_index=True)


def _render_party_list():
    st.subheader("歷屆立委不分區政黨票得票率")
    df = get_party_list_vote_trend()
    if df.empty:
        st.info("無資料（2008 年起才有不分區制度）")
        return

    totals = df.groupby("date")["votes"].sum().rename("total")
    df = df.join(totals, on="date")
    df["得票率"] = df["votes"] / df["total"] * 100

    # 只顯示曾通過門檻的政黨
    qualifying_parties = df[df["elected"] == 1]["party_name"].unique()
    major = df[df["party_name"].isin(qualifying_parties)].copy()

    pivot = major.pivot_table(index="date", columns="party_name", values="得票率", fill_value=0)
    pivot.index = pivot.index.str[:4]
    pivot.columns.name = None

    st.line_chart(pivot)
    st.caption("僅顯示至少一屆達 5% 門檻的政黨")

    # 完整資料表
    with st.expander("查看各屆完整政黨票資料"):
        display = df[["date", "party_name", "votes", "得票率", "elected"]].copy()
        display["date"] = display["date"].str[:4]
        display["votes"] = display["votes"].apply(lambda v: f"{int(v):,}")
        display["得票率"] = display["得票率"].map("{:.2f}%".format)
        display["達門檻"] = display["elected"].apply(lambda e: "✓" if e else "")
        display = display.drop(columns=["elected"]).rename(columns={
            "date": "年份", "party_name": "政黨", "votes": "得票數"
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
