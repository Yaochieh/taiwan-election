import streamlit as st
import pandas as pd
from services.election_service import get_mayoral_history
from app.utils import clean_district

PARTY_COLOR = {
    "民主進步黨": "#1B9E3E",
    "中國國民黨": "#000099",
}
PARTY_LABEL_COLOR = {
    "民主進步黨": "green",
    "中國國民黨": "blue",
}


def _party_color(party: str | None) -> str:
    if not party:
        return "gray"
    return PARTY_LABEL_COLOR.get(party, "gray")


def render():
    st.header("縣市長歷屆選舉結果")

    df = get_mayoral_history()
    if df.empty:
        st.warning("尚無縣市長選舉資料")
        return

    # 排除 地區(10, 0, 0)：資料庫匯入時的聚合佔位符，非真實單一縣市
    df = df[df["district"] != "地區(10, 0, 0)"]

    df["county"] = df["district"].apply(clean_district)
    df["year"] = df["date"].str[:4]

    # 去重複：同縣市同年份保留得票數最高的那筆（處理舊縣市代碼重疊問題）
    df = (
        df.dropna(subset=["county"])
        .sort_values("votes", ascending=False)
        .drop_duplicates(subset=["county", "year"], keep="first")
    )

    years = sorted(df["year"].unique())
    counties = sorted(df["county"].unique())

    pivot = df.pivot_table(
        index="county",
        columns="year",
        values=["candidate_name", "party_name"],
        aggfunc="first"
    )

    st.subheader("歷屆當選結果一覽")

    header_cols = ["縣市"] + years
    header_html = "".join(f"<th>{h}</th>" for h in header_cols)
    rows_html = ""

    for county in counties:
        row_html = f"<td><b>{county}</b></td>"
        for year in years:
            try:
                candidate = pivot.loc[county, ("candidate_name", year)]
                party = pivot.loc[county, ("party_name", year)]
            except KeyError:
                candidate = None
                party = None

            if pd.isna(candidate) or candidate is None:
                row_html += "<td style='color:gray'>—</td>"
            else:
                color = _party_color(party)
                party_short = party if party else "無黨籍"
                row_html += (
                    f"<td style='color:{color}'>"
                    f"<b>{candidate}</b><br><small>{party_short}</small>"
                    f"</td>"
                )
        rows_html += f"<tr>{row_html}</tr>"

    table_html = f"""
    <style>
      table.election-matrix {{
        border-collapse: collapse;
        width: 100%;
        font-size: 13px;
      }}
      table.election-matrix th, table.election-matrix td {{
        border: 1px solid #ddd;
        padding: 6px 8px;
        text-align: center;
        white-space: nowrap;
      }}
      table.election-matrix th {{
        background-color: #f0f0f0;
        font-weight: bold;
      }}
      table.election-matrix tr:nth-child(even) {{
        background-color: #fafafa;
      }}
    </style>
    <table class="election-matrix">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    st.divider()
    st.subheader("歷年各政黨縣市長席次")

    seat_df = df.dropna(subset=["county"]).copy()
    seat_df["party_group"] = seat_df["party_name"].apply(
        lambda p: p if p in ("民主進步黨", "中國國民黨") else "其他"
    )

    seat_counts = (
        seat_df.groupby(["year", "party_group"])
        .size()
        .reset_index(name="席次")
    )

    party_order = ["民主進步黨", "中國國民黨", "其他"]
    seat_pivot = seat_counts.pivot_table(
        index="year", columns="party_group", values="席次", aggfunc="sum", fill_value=0
    )
    for col in party_order:
        if col not in seat_pivot.columns:
            seat_pivot[col] = 0
    seat_pivot = seat_pivot[party_order]

    color_map = {
        "民主進步黨": PARTY_COLOR["民主進步黨"],
        "中國國民黨": PARTY_COLOR["中國國民黨"],
        "其他": "#888888",
    }

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.family"] = "Arial Unicode MS"

    fig, ax = plt.subplots(figsize=(10, 4))
    bottom = [0] * len(seat_pivot)
    x = list(seat_pivot.index)
    for party in party_order:
        vals = list(seat_pivot[party])
        ax.bar(x, vals, bottom=bottom, label=party, color=color_map[party])
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xlabel("選舉年份")
    ax.set_ylabel("席次")
    ax.set_title("歷年縣市長席次分布")
    ax.legend(loc="upper right")
    ax.set_xticks(range(len(x)))
    ax.set_xticklabels(x, rotation=45)
    plt.tight_layout()

    st.pyplot(fig)
    plt.close(fig)
