import json
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from db.queries import get_mayoral_history
from app.utils import clean_district

_GEOJSON_PATH = Path(__file__).parent.parent.parent / "assets" / "taiwan.geojson"

# GeoJSON 用舊縣名，需對應到 DB 縣名
_GEOJSON_NAME_MAP = {
    "桃園縣": "桃園市",
    "嘉義市": "嘉義市",   # 留著但 DB 無縣市長資料
}

_PARTY_COLOR = {
    "民主進步黨": "#1B9E3E",
    "中國國民黨": "#000099",
}
_OTHER_COLOR = "#888888"

_PARTY_ORDER = ["民主進步黨", "中國國民黨", "其他"]


@st.cache_data
def _load_geojson():
    with open(_GEOJSON_PATH) as f:
        geo = json.load(f)
    # 正規化縣名
    for feat in geo["features"]:
        raw = feat["properties"]["name_traditional_chinese"]
        feat["properties"]["county"] = _GEOJSON_NAME_MAP.get(raw, raw)
    return geo


@st.cache_data
def _load_mayoral():
    df = get_mayoral_history()
    df = df[df["district"] != "地區(10, 0, 0)"]
    df["county"] = df["district"].apply(clean_district)
    df["year"] = df["date"].str[:4]
    df = (
        df.dropna(subset=["county"])
        .sort_values("votes", ascending=False)
        .drop_duplicates(subset=["county", "year"], keep="first")
    )
    df["party_group"] = df["party_name"].apply(
        lambda p: p if p in ("民主進步黨", "中國國民黨") else "其他"
    )
    df["color"] = df["party_name"].apply(
        lambda p: _PARTY_COLOR.get(p, _OTHER_COLOR)
    )
    df["votes_fmt"] = df["votes"].apply(
        lambda v: f"{int(v):,}" if pd.notna(v) and v > 0 else "—"
    )
    return df


def render():
    st.header("選舉結果地圖")

    geo = _load_geojson()
    df = _load_mayoral()

    election_type = st.radio(
        "選舉類型", ["縣市長"], horizontal=True, label_visibility="collapsed"
    )

    years = sorted(df["year"].unique(), reverse=True)
    year = st.select_slider("選舉年份", options=years)

    year_df = df[df["year"] == year].copy()

    fig = _draw_map(geo, year_df, year)
    st.plotly_chart(fig, use_container_width=True)

    _draw_legend()

    st.divider()
    st.subheader(f"{year} 年各縣市當選結果")
    display = year_df[["county", "candidate_name", "party_name", "votes_fmt"]].rename(
        columns={"county": "縣市", "candidate_name": "當選人", "party_name": "政黨", "votes_fmt": "得票數"}
    )
    st.dataframe(display.sort_values("縣市"), use_container_width=True, hide_index=True)


def _draw_map(geo, year_df, year):
    # 建立完整縣市列表（確保沒資料的縣市也顯示）
    all_counties = [
        f["properties"]["county"] for f in geo["features"]
    ]
    base = pd.DataFrame({"county": all_counties})
    merged = base.merge(year_df[["county", "party_group", "candidate_name", "party_name", "votes_fmt"]], on="county", how="left")
    merged["party_group"] = merged["party_group"].fillna("無資料")
    merged["candidate_name"] = merged["candidate_name"].fillna("—")
    merged["party_name"] = merged["party_name"].fillna("—")
    merged["votes_fmt"] = merged["votes_fmt"].fillna("—")

    category_orders = _PARTY_ORDER + ["其他", "無資料"]
    color_map = {
        "民主進步黨": _PARTY_COLOR["民主進步黨"],
        "中國國民黨": _PARTY_COLOR["中國國民黨"],
        "其他": _OTHER_COLOR,
        "無資料": "#cccccc",
    }

    fig = px.choropleth(
        merged,
        geojson=geo,
        locations="county",
        featureidkey="properties.county",
        color="party_group",
        color_discrete_map=color_map,
        category_orders={"party_group": category_orders},
        hover_name="county",
        hover_data={
            "candidate_name": True,
            "party_name": True,
            "votes_fmt": True,
            "party_group": False,
            "county": False,
        },
        labels={
            "candidate_name": "當選人",
            "party_name": "政黨",
            "votes_fmt": "得票數",
            "party_group": "政黨",
        },
        title=f"{year} 年縣市長選舉結果",
    )
    fig.update_geos(
        fitbounds="locations",
        visible=False,
    )
    fig.update_layout(
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
        height=600,
        legend_title_text="政黨",
    )
    return fig


def _draw_legend():
    cols = st.columns(3)
    data = [
        ("民主進步黨", _PARTY_COLOR["民主進步黨"]),
        ("中國國民黨", _PARTY_COLOR["中國國民黨"]),
        ("其他/無黨籍", _OTHER_COLOR),
    ]
    for col, (label, color) in zip(cols, data):
        col.markdown(
            f"<span style='display:inline-block;width:14px;height:14px;"
            f"background:{color};border-radius:2px;margin-right:6px;vertical-align:middle'></span>"
            f"{label}",
            unsafe_allow_html=True,
        )
