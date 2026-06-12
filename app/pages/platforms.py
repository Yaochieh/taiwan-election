import streamlit as st
import pandas as pd
from db.queries import (
    get_elections_with_platforms,
    get_platforms_by_election,
    get_platform_sources,
)


def render():
    st.header("候選人政見")
    st.caption("資料來源：中選會選舉公報")

    elections = get_elections_with_platforms()
    if elections.empty:
        st.info("目前尚無政見資料")
        return

    # 選擇選舉
    options = {
        f"{row['date'][:4]} {row['name']}": row["election_id"]
        for _, row in elections.iterrows()
    }
    selected_label = st.selectbox("選擇選舉", list(options.keys()))
    election_id = int(options[selected_label])

    df = get_platforms_by_election(election_id)
    if df.empty:
        st.info("此選舉尚無政見資料")
        return

    # 統計
    candidates = df["candidate_name"].unique()
    st.metric("有政見的候選人", f"{len(candidates)} 位", f"共 {len(df)} 條政見")

    st.divider()

    # 按候選人顯示
    for cand_name in candidates:
        cand_data = df[df["candidate_name"] == cand_name]
        candidate_id = int(cand_data.iloc[0]["candidate_id"])
        party = cand_data.iloc[0]["party_name"] or "無黨籍"
        color = cand_data.iloc[0]["color_hex"] or "#888888"

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"### <span style='color:{color}'>{cand_name}</span> "
                    f"<small style='color:#888; font-weight:normal'>{party}</small>",
                    unsafe_allow_html=True,
                )
            with col2:
                st.caption(f"{len(cand_data)} 條政見")

            for _, row in cand_data.iterrows():
                seq = row["seq"]
                content = row["content"]
                st.markdown(f"**{seq}.** {content}")

            # 政見來源
            sources = get_platform_sources(candidate_id, election_id)
            if not sources.empty:
                with st.expander("📎 資料來源"):
                    for _, src in sources.iterrows():
                        desc = src["description"] or src["source_type"]
                        if src["url"]:
                            st.markdown(f"- [{desc}]({src['url']})")
                        else:
                            st.markdown(f"- {desc}")
                        if src["local_path"]:
                            st.caption(f"本地檔案：`{src['local_path']}`")
