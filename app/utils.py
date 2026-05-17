import re

# 中選會縣市代碼對照（elbase.csv 的縣市別欄位）
COUNTY_CODE_MAP = {
    1:  "台北市",
    2:  "高雄市",
    3:  "基隆市",
    4:  "台中市",
    5:  "台南市",
    6:  "新竹市",
    7:  "嘉義市",
    10: "台北縣",
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
    63: "台北市",   # 2010 後直轄市重組
    64: "新北市",
    65: "台中市",
    66: "台南市",
    67: "高雄市",
    68: "桃園市",
    10: "新北市",   # 台北縣改制
    0:  "全國",
}


def clean_district(district: str | None) -> str | None:
    """將 '地區(X, 0, 0)' 格式轉成縣市中文名稱"""
    if not district:
        return district
    m = re.match(r"地區\((\d+),\s*0,\s*0\)", district)
    if m:
        code = int(m.group(1))
        return COUNTY_CODE_MAP.get(code, district)
    return district
