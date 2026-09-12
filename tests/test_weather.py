# get_weather 测试 — mock httpx.Client 的返回值（仅测试允许 mock）
from app.tools.weather import get_weather

GEO_PAYLOAD = {"results": [{"latitude": 39.9042, "longitude": 116.4074}]}
FORECAST_PAYLOAD = {
    "daily": {
        "time": ["2026-08-19", "2026-08-20", "2026-08-21"],
        "weather_code": [0, 61, 95],
        "temperature_2m_max": [30.0, 28.0, 25.0],
        "temperature_2m_min": [20.0, 21.0, 18.0],
        "precipitation_probability_max": [10, 80, 50],
    }
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, geo_payload, forecast_payload):
        self.geo_payload = geo_payload
        self.forecast_payload = forecast_payload

    def get(self, url, params=None, **kwargs):
        if "geocoding" in url:
            return FakeResponse(self.geo_payload)
        return FakeResponse(self.forecast_payload)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_weather_success(monkeypatch):
    fake = FakeClient(GEO_PAYLOAD, FORECAST_PAYLOAD)
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: fake)

    result = get_weather({"city": "北京", "date": "2026-08-20"}, None, None)
    assert result["success"] is True
    assert result["city"] == "北京"
    assert result["date"] == "2026-08-20"
    assert result["weather"] == "雨"
    assert result["temp_max"] == 28.0
    assert result["temp_min"] == 21.0
    assert result["precip_prob"] == 80


def test_weather_default_date(monkeypatch):
    from datetime import datetime

    fake = FakeClient(GEO_PAYLOAD, FORECAST_PAYLOAD)
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: fake)
    # 默认「今天」随真实时钟漂移，会落进 mock 预报范围（固定 2026-08）之外；
    # 固定 now 使默认日期断言确定
    monkeypatch.setattr(
        "app.tools.weather.datetime",
        type("FakeDatetime", (), {"now": classmethod(lambda cls: datetime(2026, 8, 20))}),
    )

    result = get_weather({"city": "beijing"}, None, None)
    assert result["success"] is True
    assert result["date"] == "2026-08-20"


def test_weather_city_not_found(monkeypatch):
    fake = FakeClient({"results": []}, {})
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: fake)

    result = get_weather({"city": "不存在城市xyz"}, None, None)
    assert result["success"] is False
    assert "找不到城市" in result["error"]


def test_weather_service_error(monkeypatch):
    class BoomClient(FakeClient):
        def get(self, url, params=None, **kwargs):
            raise RuntimeError("network down")

    fake = BoomClient(GEO_PAYLOAD, FORECAST_PAYLOAD)
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: fake)

    result = get_weather({"city": "北京"}, None, None)
    assert result["success"] is False
    assert "天气服务不可用" in result["error"]
