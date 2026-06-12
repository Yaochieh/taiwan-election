import streamlit as st
import pandas as pd
from db.queries import (
    get_elections_with_platforms,
    get_platforms_by_election,
    get_platform_sources,
    get_candidates_with_platform_status,
    get_districts_for_election,
)
from app.utils import clean_district


def render():
    st.header("候選人政見")
    st.caption(
        "本平台政見資料皆來自 [中選會選舉公報](https://bulletin.cec.gov.tw)，"
        "點擊每位候選人下方的「資料來源」可查證原始 PDF。"
        "若候選人未在選舉公報刊登政見，將特別標註，民眾可至公報原檔自行確認。"
    )

    elections = get_elections_with_platforms()
    if elections.empty:
        st.info("目前尚無政見資料")
        return

    # 選舉
    col_e, col_d = st.columns([3, 2])
    with col_e:
        options = {
            f"{row['date'][:4]} {row['name']}": row["election_id"]
            for _, row in elections.iterrows()
        }
        selected_label = st.selectbox("選擇選舉", list(options.keys()))
        election_id = int(options[selected_label])

    # 選區
    with col_d:
        districts = get_districts_for_election(election_id)
        district_options = ["全部"] + districts["district"].tolist()
        # 用 clean_district 美化
        district_labels = {
            d: (clean_district(d) or d) if d != "全部" else "全部"
            for d in district_options
        }
        selected_district = st.selectbox(
            "選區（縣市）",
            district_options,
            format_func=lambda d: district_labels[d],
        )

    district_filter = None if selected_district == "全部" else selected_district
    df = get_candidates_with_platform_status(election_id, district_filter)

    if df.empty:
        st.info("此選舉/選區尚無候選人資料")
        return

    # 統計
    total = len(df)
    with_platforms = int((df["platform_count"] > 0).sum())
    without_platforms = total - with_platforms

    col1, col2, col3 = st.columns(3)
    col1.metric("候選人", total)
    col2.metric("有刊登政見", with_platforms)
    col3.metric("未刊登政見", without_platforms,
                delta=None,
                help="表示該候選人未在中選會選舉公報刊登政見內容")

    st.divider()

    # 政見內容
    platforms_df = get_platforms_by_election(election_id)

    for _, cand in df.iterrows():
        cid = int(cand["candidate_id"])
        cname = cand["candidate_name"]
        party = cand["party_name"] or "無黨籍"
        color = cand["color_hex"] or "#888888"
        elected = bool(cand["elected"])
        votes = cand["votes"]
        n_platforms = int(cand["platform_count"])
        district = cand.get("district", "")

        # district label
        district_label = clean_district(district) or district

        with st.container(border=True):
            # Header
            header_l, header_r = st.columns([4, 1])
            with header_l:
                badge = "🏆 當選　" if elected else ""
                st.markdown(
                    f"### {badge}<span style='color:{color}'>{cname}</span> "
                    f"<small style='color:#888; font-weight:normal'>{party}　"
                    f"{district_label}　"
                    f"{f'得票數 {int(votes):,}' if pd.notna(votes) and votes else ''}</small>",
                    unsafe_allow_html=True,
                )
            with header_r:
                if n_platforms > 0:
                    st.success(f"刊登 {n_platforms} 條政見")
                else:
                    st.warning("⚠️ 未刊登政見")

            if n_platforms > 0:
                cand_pl = platforms_df[platforms_df["candidate_id"] == cid].sort_values("seq")
                for _, p in cand_pl.iterrows():
                    st.markdown(f"**{p['seq']}.** {p['content']}")
            else:
                st.markdown(
                    "_此候選人未於中選會選舉公報刊登政見內容。_"
                    "如需了解其政策主張，建議直接造訪候選人官方網站或社群媒體。"
                )

            # 資料來源
            sources = get_platform_sources(cid, election_id)
            if not sources.empty:
                with st.expander("📎 資料來源"):
                    for _, src in sources.iterrows():
                        desc = src["description"] or src["source_type"]
                        if src["url"]:
                            st.markdown(f"- [{desc}]({src['url']})")
                        else:
                            st.markdown(f"- {desc}")
                        fetched = src["fetched_at"]
                        if pd.notna(fetched) and fetched:
                            st.caption(f"資料擷取時間：{fetched}")
            else:
                st.caption("尚未連結資料來源")
