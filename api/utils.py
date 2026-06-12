"""API 共用工具。"""
import math
from typing import Any

import pandas as pd


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """
    安全地把 DataFrame 轉成 list[dict]，處理：
      - NaN / pd.NA / None → None
      - numpy/pyarrow scalar → Python 原生型別
    避免 Pydantic ResponseValidationError。
    """
    if df is None or df.empty:
        return []

    # 先把所有 NaN / pd.NA 替換成 None
    df = df.astype(object).where(pd.notnull(df), None)

    records = df.to_dict(orient="records")
    return [_normalize(r) for r in records]


def _normalize(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = _normalize_value(v)
    return out


def _normalize_value(v: Any) -> Any:
    if v is None:
        return None
    # pd.NA / NaN
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    # numpy scalars
    if hasattr(v, "item"):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    # float NaN
    if isinstance(v, float) and math.isnan(v):
        return None
    return v
