import re

COUNTY_CODE_MAP = {
    1:  "台北市",
    2:  "高雄市",
    3:  "基隆市",
    4:  "台中市",
    5:  "台南市",
    6:  "新竹市",
    7:  "嘉義市",
    9:  "金門縣",
    10: "新北市",
    14: "宜蘭縣",
    15: "桃園縣",
    16: "新竹縣",
    17: "苗栗縣",
    18: "台中縣",
    19: "彰化縣",
    20: "南投縣",
    21: "雲林縣",
    22: "嘉義縣",
    23: "台南縣",
    24: "高雄縣",
    25: "屏東縣",
    26: "台東縣",
    27: "花蓮縣",
    28: "澎湖縣",
    63: "台北市",
    64: "高雄市",
    65: "新北市",
    66: "台中市",
    67: "台南市",
    68: "桃園市",
    0:  "全國",
}

TOWNSHIP_TO_COUNTY = {
    "七美鄉": "澎湖縣",
    "五峰鄉": "新竹縣",
    "仁愛鄉": "南投縣",
    "信義區": "基隆市",
    "卓溪鄉": "花蓮縣",
    "南澳鄉": "宜蘭縣",
    "溪州鄉": "彰化縣",
    "牡丹鄉": "屏東縣",
    "水林鄉": "雲林縣",
    "阿里山鄉": "嘉義縣",
    "泰安鄉": "苗栗縣",
    "香山區": "新竹市",
    "蘭嶼鄉": "台東縣",
    "烏坵鄉": "金門縣",
    "東引鄉": "連江縣",
    "山地門鄉": "屏東縣",
    "滿洲鄉": "屏東縣",
}


def clean_district(district) -> str | None:
    """將 '地區(X, 0, 0)' 格式或鄉鎮市區名稱轉成縣市中文名稱"""
    if district is None:
        return None
    # pandas + pyarrow 後端可能傳入 pa.Scalar 或 NaN，統一轉成 str
    try:
        district = str(district)
    except Exception:
        return None
    if not district or district in ("nan", "None", "<NA>"):
        return None
    m = re.match(r"地區\((\d+),\s*0,\s*0\)", district)
    if m:
        code = int(m.group(1))
        return COUNTY_CODE_MAP.get(code, district)
    if district in TOWNSHIP_TO_COUNTY:
        return TOWNSHIP_TO_COUNTY[district]
    return district


def county_from_district(district: str | None) -> str | None:
    """回傳任意選區格式對應的縣市名稱"""
    if not district:
        return None
    result = clean_district(district)
    if result == district:
        return None
    return result
