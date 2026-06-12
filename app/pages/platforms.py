from pathlib import Path
import streamlit as st
import pandas as pd
from db.queries import (
    get_elections_with_platforms,
    get_platforms_by_election,
    get_platform_sources,
    get_candidates_with_platform_status,
    get_districts_for_election,
    get_platform_images,
)
from app.utils import clean_district

ROOT = Path(__file__).parent.parent.parent


def render():
    st.header("候選人政見")
    st.caption(
        "資料來源：[中選會選舉公報](https://bulletin.cec.gov.tw)。"
        "點擊每位候選人下方的「📎 資料來源」可查證原始 PDF。"
        "若候選人提交為圖檔版政見，將以原圖呈現；"
        "若候選人完全未繳交政見，將特別標註，民眾可至公報自行確認。"
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

    with col_d:
        districts = get_districts_for_election(election_id)
        district_options = ["全部"] + districts["district"].tolist()
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
    with_text = int((df["platform_count"] > 0).sum())
    with_image_only = int(((df["platform_count"] == 0) & (df["image_count"] > 0)).sum())
    without_any = total - with_text - with_image_only

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("候選人", total)
    c2.metric("文字政見", with_text)
    c3.metric("圖片政見", with_image_only)
    c4.metric("完全未繳", without_any,
              help="既無文字政見也無圖片政見，候選人未提交任何資料至選舉公報")

    st.divider()

    platforms_df = get_platforms_by_election(election_id)

    for _, cand in df.iterrows():
        cid = int(cand["candidate_id"])
        cname = cand["candidate_name"]
        party = cand["party_name"] or "無黨籍"
        color = cand["color_hex"] or "#888888"
        elected = bool(cand["elected"])
        votes = cand["votes"]
        n_text = int(cand["platform_count"])
        n_image = int(cand["image_count"])
        district = cand.get("district", "")

        district_label = clean_district(district) or district

        with st.container(border=True):
            header_l, header_r = st.columns([4, 1])
            with header_l:
                badge = "🏆 當選　" if elected else ""
                votes_str = f"得票數 {int(votes):,}" if pd.notna(votes) and votes else ""
                st.markdown(
                    f"### {badge}<span style='color:{color}'>{cname}</span> "
                    f"<small style='color:#888; font-weight:normal'>{party}　"
                    f"{district_label}　{votes_str}</small>",
                    unsafe_allow_html=True,
                )
            with header_r:
                if n_text > 0:
                    st.success(f"文字政見 {n_text} 條")
                elif n_image > 0:
                    st.info(f"圖片政見 {n_image} 張")
                else:
                    st.warning("⚠️ 完全未繳交")

            # 文字政見
            if n_text > 0:
                cand_pl = platforms_df[platforms_df["candidate_id"] == cid].sort_values("seq")
                for _, p in cand_pl.iterrows():
                    st.markdown(f"**{p['seq']}.** {p['content']}")

            # 圖片政見
            if n_image > 0:
                images = get_platform_images(cid, election_id)
                if n_text == 0:
                    st.markdown(
                        "_此候選人提交的是**圖片版**政見（含設計排版），以下為公報原圖：_"
                    )
                else:
                    st.markdown("_補充：候選人另提供圖片版政見：_")
                for _, img in images.iterrows():
                    img_path = ROOT / img["local_path"]
                    if img_path.exists():
                        st.image(str(img_path), use_container_width=True)
                    else:
                        st.caption(f"⚠️ 圖檔不存在：{img['local_path']}")

            # 完全未繳
            if n_text == 0 and n_image == 0:
                st.markdown(
                    "_此候選人**未於中選會選舉公報刊登任何政見內容**。_"
                    "公報之政見刊登屬候選人自由意願，民眾可至選舉公報原檔查證。"
                )

            # 資料來源
            sources = get_platform_sources(cid, election_id)
            if not sources.empty:
                with st.expander("📎 資料來源"):
                    # 去重複（同一 URL 可能多次記錄）
                    seen_urls = set()
                    for _, src in sources.iterrows():
                        url = src["url"]
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        desc = src["description"] or src["source_type"]
                        if url:
                            st.markdown(f"- [{desc}]({url})")
                        else:
                            st.markdown(f"- {desc}")
