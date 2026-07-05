from fastapi import APIRouter, HTTPException
from db import queries

router = APIRouter()


@router.get("/{name}")
def person_profile(name: str):
    """聚合同姓名候選人的所有參選紀錄、政見、政黨變遷。"""
    profile = queries.get_person_profile(name)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到此人物")
    return profile


@router.get("/{name}/targets")
def person_targets(name: str):
    """取得該政治人物的政見追蹤目標（含 baseline、target、進度資料點）。"""
    return queries.get_person_targets(name)


@router.get("/{name}/topic-distribution")
def person_topic_distribution(name: str):
    """該政治人物各主題政見的分布（用於雷達圖）"""
    return queries.get_person_topic_distribution(name)


@router.get("/{name}/bill-matches")
def person_bill_matches(name: str):
    """立委政見×立院提案 關鍵詞對照（相關提案，非兌現認定）"""
    return queries.get_person_bill_matches(name)
