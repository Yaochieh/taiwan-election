from fastapi import APIRouter, Query
from db import queries

router = APIRouter()


@router.get("")
def list_topics():
    """所有主題與政見數量"""
    return queries.list_platform_topics()


@router.get("/{topic_name}")
def topic_detail(
    topic_name: str,
    election_type: str | None = Query(None, description="篩選類型：presidential/legislative/mayoral/council"),
    party: str | None = Query(None, description="篩選政黨"),
    person: str | None = Query(None, description="篩選候選人"),
    year_from: int | None = Query(None),
    year_to: int | None = Query(None),
):
    """主題下的所有政見（可按多維度篩選）"""
    return queries.get_topic_platforms(
        topic_name, election_type=election_type, party=party,
        person=person, year_from=year_from, year_to=year_to,
    )


@router.get("/{topic_name}/stats")
def topic_stats(topic_name: str):
    """主題的彙總統計（年度趨勢、各黨次數、最常提及者）"""
    return queries.get_topic_stats(topic_name)
