# search_hotel — 真实酒店查询（URL 与密钥由用户自填，未配置时明确报错，绝不伪造）
import httpx

from ..user_cfg import get_hotel_cfg
from .registry import tool


@tool(
    name="search_hotel",
    description="查询酒店（需要用户已配置酒店服务的 URL 与密钥）",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "budget": {"type": "number", "description": "预算上限，可选"},
        },
        "required": ["city"],
    },
)
def search_hotel(args, user, db):
    cfg = get_hotel_cfg(db, user.id)
    base_url = cfg["base_url"]
    api_key = cfg["api_key"]
    if not base_url or not api_key:
        return {"success": False, "error": "订酒店服务未配置：请在「设置」页填写你自己的 URL 与密钥后使用"}

    city = args.get("city")
    params = {"city": city, "date": args.get("date")}
    if args.get("budget") is not None:
        params["budget"] = args["budget"]

    try:
        resp = httpx.Client(timeout=15).get(
            base_url,
            params=params,
            headers={"Authorization": "Bearer " + api_key},
        )
        resp.raise_for_status()
    except Exception as e:
        return {"success": False, "error": f"酒店服务请求失败: {e}"}

    # 保留原始结构——各家 API 格式由用户自填，不强转
    return {"success": True, "raw": resp.json()}
