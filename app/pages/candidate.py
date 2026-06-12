import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
matplotlib.rcParams["font.family"] = "Arial Unicode MS"

from services.candidate_service import get_candidates_by_election
from db.queries import get_all_elections, get_total_votes_by_election, search_candidates
from app.utils import clean_district

_ELECTION_TYPE_ZH = {
    "presidential": "總統",
    "legislative":  "立委",
    "mayoral":      "縣市長",
    "council":      "議員",
}


def render():
    st.header("候選人查詢")

    # profile view 優先渲染
    if st.session_state.get("profile_candidate"):
        _render_profile(st.session_state["profile_candidate"])
        return

    tab1, tab2 = st.tabs(["依選舉查詢", "跨選舉搜尋"])
    with tab1:
        _render_by_election()
    with tab2:
        _render_search()


# ── Profile view ───────────────────────────────────────────────────────────────

def _render_profile(name: str):
    if st.button("← 返回搜尋"):
        st.session_state["profile_candidate"] = None
        st.rerun()

    df = search_candidates(name)
    # 完全比對（搜尋可能模糊，這裡只顯示精確姓名）
    df = df[df["name"] == name]
    if df.empty:
        st.warning(f"找不到「{name}」的資料")
        return

    df = df.sort_values("date")
    total_races = len(df)
    total_wins = int(df["elected"].sum())
    latest_party = df.iloc[-1]["party_name"] or "無黨籍"
    earliest_year = df.iloc[0]["date"][:4]
    latest_year = df.iloc[-1]["date"][:4]

    # ── Header ─────────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("姓名", name)
    col2.metric("最近政黨", latest_party)
    col3.metric("參選次數", total_races)
    col4.metric("當選次數", total_wins)

    st.divider()

    # ── 政黨歷程 ────────────────────────────────────────────────────────────────
    parties = df[["date", "party_name"]].copy()
    parties["year"] = parties["date"].str[:4]
    parties["party_name"] = parties["party_name"].fillna("無黨籍")
    party_changes = parties[parties["party_name"] != parties["party_name"].shift()]

    if len(party_changes) > 1:
        st.subheader("政黨歷程")
        timeline_parts = []
        for _, row in party_changes.iterrows():
            timeline_parts.append(f"{row['year']} {row['party_name']}")
        st.markdown("　→　".join(timeline_parts))
        st.divider()

    # ── 選舉記錄 ────────────────────────────────────────────────────────────────
    st.subheader("歷次參選記錄")
    display = pd.DataFrame({
        "年份":    df["date"].str[:4].values,
        "選舉":    df["election_name"].values,
        "類型":    df["election_type"].map(_ELECTION_TYPE_ZH).values,
        "角色":    df["role"].fillna("").values,
        "政黨":    df["party_name"].fillna("無黨籍").values,
        "選區":    df["district"].apply(clean_district).values,
        "得票數":  df["votes"].apply(
            lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—"
        ).values,
        "當選":    df["elected"].apply(lambda v: "✓" if v == 1 else "").values,
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    # ── 得票趨勢圖（需 3+ 筆有票數的資料）──────────────────────────────────────
    vote_df = df[df["votes"].notna() & (df["votes"] > 0)].copy()
    if len(vote_df) >= 3:
        st.divider()
        st.subheader("歷次得票趨勢")

        fig, ax = plt.subplots(figsize=(8, 3))
        x = vote_df["date"].str[:4].tolist()
        y = vote_df["votes"].astype(int).tolist()
        elected_mask = vote_df["elected"].tolist()

        ax.plot(x, y, marker="o", color="#555555", linewidth=1.5)
        for xi, yi, win in zip(x, y, elected_mask):
            color = "#1B9E3E" if win == 1 else "#cc3333"
            ax.scatter(xi, yi, color=color, zorder=5, s=60)

        ax.set_ylabel("得票數")
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{int(v):,}")
        )
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.3)

        from matplotlib.lines import Line2D
        legend = [
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#1B9E3E", markersize=8, label="當選"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#cc3333",  markersize=8, label="落選"),
        ]
        ax.legend(handles=legend)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)


# ── 依選舉查詢 Tab ──────────────────────────────────────────────────────────────

def _render_by_election():
    elections_df = get_all_elections()
    if elections_df.empty:
        st.warning("尚無選舉資料")
        return

    elections_df = elections_df.sort_values("date", ascending=False)

    def _label(row):
        base = f"{row['date'][:4]} {row['name']}"
        return f"{base}（{row['description']}）" if row.get("description") else base

    options = {_label(row): row["election_id"] for _, row in elections_df.iterrows()}
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


# ── 跨選舉搜尋 Tab ──────────────────────────────────────────────────────────────

def _render_search():
    st.subheader("跨選舉候選人搜尋")
    query = st.text_input("輸入候選人姓名（支援部分比對）", placeholder="例如：陳水扁")

    if not query:
        st.caption("請輸入姓名進行搜尋")
        return

    df = search_candidates(query)
    if df.empty:
        st.info(f"找不到「{query}」相關的候選人記錄")
        return

    st.success(f"共找到 {len(df)} 筆記錄")

    grouped = df.groupby("name")
    for name, group in grouped:
        elected_count = int(group["elected"].sum())
        col_title, col_btn = st.columns([5, 1])
        col_title.markdown(f"**{name}**　{len(group)} 次參選，{elected_count} 次當選")
        if col_btn.button("個人頁面 →", key=f"profile_{name}"):
            st.session_state["profile_candidate"] = name
            st.rerun()

        display = pd.DataFrame({
            "年份":   group["date"].str[:4].values,
            "選舉":   group["election_name"].values,
            "政黨":   group["party_name"].fillna("無").values,
            "角色":   group["role"].fillna("").values,
            "選區":   group["district"].apply(clean_district).values,
            "得票數": group["votes"].apply(
                lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—"
            ).values,
            "當選":   group["elected"].apply(lambda v: "✓" if v == 1 else "").values,
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.divider()


# ── 共用表格 ────────────────────────────────────────────────────────────────────

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
