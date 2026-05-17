import streamlit as st
from services.election_service import get_all_elections

TYPE_ZH = {
    "presidential": "總統",
    "legislative":  "立委",
    "mayoral":      "縣市長",
    "council":      "議員",
}

def render():
    st.header("選舉時程")
    df = get_all_elections()
    if df.empty:
        st.info("目前尚無資料，請執行 scripts/import_votedata.py 匯入資料。")
        return

    col1, col2 = st.columns(2)
    with col1:
        type_options = ["全部"] + list(TYPE_ZH.values())
        type_filter = st.selectbox("選舉類型", type_options)
    with col2:
        year_options = ["全部"] + sorted(
            df["date"].str[:4].unique().tolist(), reverse=True
        )
        year_filter = st.selectbox("年份", year_options)

    display = df.copy()
    if type_filter != "全部":
        type_key = {v: k for k, v in TYPE_ZH.items()}[type_filter]
        display = display[display["type"] == type_key]
    if year_filter != "全部":
        display = display[display["date"].str.startswith(year_filter)]

    display = display.sort_values("date", ascending=False)
    display["類型"] = display["type"].map(TYPE_ZH)
    display["選舉名稱"] = display.apply(
        lambda r: f"{r['name']}（{r['description']}）" if r.get("description") else r["name"],
        axis=1
    )
    display = display.rename(columns={"date": "投票日"})[
        ["投票日", "類型", "選舉名稱"]
    ]

    st.caption(f"共 {len(display)} 筆")
    st.dataframe(display, use_container_width=True, hide_index=True)
