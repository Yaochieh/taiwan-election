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
