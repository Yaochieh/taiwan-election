import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.rcParams["font.family"] = "Arial Unicode MS"

from db.queries import (
    get_presidential_vote_trend,
    get_party_list_vote_trend,
    get_mayoral_history,
    get_connection,
)
from app.utils import clean_district

OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def plot_presidential_trend():
    df = get_presidential_vote_trend()
    if df.empty:
        print("總統選舉資料不足，跳過")
        return

    df["year"] = df["date"].str[:4]
    totals = df.groupby("year")["votes"].sum().rename("total")
    df = df.join(totals, on="year")
    df["share"] = df["votes"] / df["total"] * 100

    target_parties = ["民主進步黨", "中國國民黨"]
    party_df = df[df["party_name"].isin(target_parties)]

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = {"民主進步黨": "#1B9E3E", "中國國民黨": "#000099"}

    for party, group in party_df.groupby("party_name"):
        year_share = group.groupby("year")["share"].sum()
        ax.plot(year_share.index, year_share.values, marker="o",
                label=party, color=colors.get(party, "gray"))
        for x, y in zip(year_share.index, year_share.values):
            ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=9)

    ax.set_title("歷屆總統選舉民進黨 vs 國民黨得票率")
    ax.set_xlabel("選舉年份")
    ax.set_ylabel("得票率 (%)")
    ax.legend()
    ax.set_ylim(0, 70)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()
    out = OUTPUT_DIR / "presidential_trend.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"已儲存：{out}")


def plot_party_list_trend():
    df = get_party_list_vote_trend()
    if df.empty:
        print("不分區資料不足，跳過")
        return

    df["year"] = df["date"].str[:4]
    totals = df.groupby("year")["votes"].sum().rename("total")
    df = df.join(totals, on="year")
    df["share"] = df["votes"] / df["total"] * 100

    top_parties = (
        df.groupby("party_name")["votes"].sum()
        .sort_values(ascending=False)
        .head(5)
        .index.tolist()
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    palette = ["#1B9E3E", "#000099", "#28C8C8", "#FF6600", "#888888"]
    for i, party in enumerate(top_parties):
        group = df[df["party_name"] == party]
        year_share = group.groupby("year")["share"].sum().sort_index()
        ax.plot(year_share.index, year_share.values, marker="o",
                label=party, color=palette[i % len(palette)])

    ax.set_title("歷屆立委不分區政黨票得票率（前五大政黨）")
    ax.set_xlabel("選舉年份")
    ax.set_ylabel("得票率 (%)")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()
    out = OUTPUT_DIR / "party_list_trend.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"已儲存：{out}")


def plot_mayoral_seats_by_year():
    df = get_mayoral_history()
    if df.empty:
        print("縣市長資料不足，跳過")
        return

    df["county"] = df["district"].apply(clean_district)
    df = df.dropna(subset=["county"])
    df["year"] = df["date"].str[:4]
    df["party_group"] = df["party_name"].apply(
        lambda p: p if p in ("民主進步黨", "中國國民黨") else "其他"
    )

    seat_counts = (
        df.groupby(["year", "party_group"])
        .size()
        .reset_index(name="席次")
    )
    party_order = ["民主進步黨", "中國國民黨", "其他"]
    pivot = seat_counts.pivot_table(
        index="year", columns="party_group", values="席次", aggfunc="sum", fill_value=0
    )
    for col in party_order:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot[party_order]

    colors = {"民主進步黨": "#1B9E3E", "中國國民黨": "#000099", "其他": "#888888"}
    fig, ax = plt.subplots(figsize=(10, 5))
    x = list(pivot.index)
    bottom = [0] * len(x)
    for party in party_order:
        vals = list(pivot[party])
        ax.bar(x, vals, bottom=bottom, label=party, color=colors[party])
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_title("歷年縣市長選舉席次分布")
    ax.set_xlabel("選舉年份")
    ax.set_ylabel("席次")
    ax.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    out = OUTPUT_DIR / "mayoral_seats_by_year.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"已儲存：{out}")


def plot_candidate_party_distribution():
    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT p.name AS party_name, COUNT(*) AS elected_count
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE er.elected = 1
            GROUP BY p.name
            ORDER BY elected_count DESC
            LIMIT 10
            """,
            conn
        )

    if df.empty:
        print("當選資料不足，跳過")
        return

    df["party_name"] = df["party_name"].fillna("無黨籍")
    colors_map = {
        "民主進步黨": "#1B9E3E",
        "中國國民黨": "#000099",
        "台灣民眾黨": "#28C8C8",
    }
    bar_colors = [colors_map.get(p, "#888888") for p in df["party_name"]]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(df["party_name"][::-1], df["elected_count"][::-1], color=bar_colors[::-1])
    ax.set_title("歷年各政黨當選人數（前十大政黨）")
    ax.set_xlabel("當選人數")
    for i, (val, name) in enumerate(zip(df["elected_count"][::-1], df["party_name"][::-1])):
        ax.text(val + 0.5, i, str(val), va="center", fontsize=9)
    plt.tight_layout()
    out = OUTPUT_DIR / "candidate_party_distribution.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"已儲存：{out}")


if __name__ == "__main__":
    print("開始產生靜態圖表...")
    plot_presidential_trend()
    plot_party_list_trend()
    plot_mayoral_seats_by_year()
    plot_candidate_party_distribution()
    print("完成！")
