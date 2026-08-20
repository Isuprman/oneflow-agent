# get_weather — 真实天气查询，Open-Meteo 免费 API，无 Key
from datetime import datetime

import httpx

from .registry import tool


def weather_code_to_cn(code):
    if code == 0:
        return "晴"
    if code in (1, 2):
        return "多云"
    if code == 3:
        return "阴"
    if code in (45, 48):
        return "雾"
    if code in (51, 53, 55, 56, 57):
        return "毛毛雨"
    if code in (61, 63, 65, 66, 67):
        return "雨"
    if 71 <= code <= 77:
        return "雪"
    if 80 <= code <= 82:
        return "阵雨"
    if 95 <= code <= 99:
        return "雷暴"
    return "未知"


@tool(
    name="get_weather",
    description="查询城市天气（中文描述），支持中文或拼音城市名",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名，中文或拼音"},
            "date": {"type": "string", "description": "YYYY-MM-DD，默认今天"},
        },
        "required": ["city"],
    },
)
def get_weather(args, user, db):
    city = args.get("city")
    if not city:
        return {"success": False, "error": "缺少城市"}
    date = args.get("date") or datetime.now().strftime("%Y-%m-%d")
    return query_weather(city, date)


def query_weather(city: str, date: str) -> dict:
    """查询指定城市/日期天气（工具与调度器关怀规则共用）。"""
    with httpx.Client(timeout=10) as client:
        # 1. 地理编码：城市名 -> 经纬度
        try:
            geo = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "format": "json", "language": "zh"},
            )
            geo.raise_for_status()
        except Exception as e:
            return {"success": False, "error": f"天气服务不可用: {e}"}

        results = (geo.json() or {}).get("results") or []
        if not results:
            return {"success": False, "error": f"找不到城市: {city}"}
        latitude = results[0]["latitude"]
        longitude = results[0]["longitude"]

        # 2. 预报
        try:
            fc = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": 3,
                },
            )
            fc.raise_for_status()
        except Exception as e:
            return {"success": False, "error": f"天气服务不可用: {e}"}

        daily = fc.json().get("daily") or {}
        times = daily.get("time") or []
        if date not in times:
            return {"success": False, "error": f"该日期不在预报范围内: {date}"}
        idx = times.index(date)

        codes = daily.get("weather_code") or []
        maxes = daily.get("temperature_2m_max") or []
        mins = daily.get("temperature_2m_min") or []
        probs = daily.get("precipitation_probability_max") or []

        weather_cn = weather_code_to_cn(codes[idx]) if idx < len(codes) else "未知"
        temp_max = maxes[idx] if idx < len(maxes) else None
        temp_min = mins[idx] if idx < len(mins) else None
        precip_prob = probs[idx] if idx < len(probs) else None

    return {
        "success": True,
        "city": city,
        "date": date,
        "weather": weather_cn,
        "temp_max": temp_max,
        "temp_min": temp_min,
        "precip_prob": precip_prob,
    }
