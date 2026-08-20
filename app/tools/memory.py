# OneFlow 长期记忆工具
from .registry import tool


@tool(
    name="remember",
    description="记住一条关于用户的长期信息（偏好/事实/结论），供以后的问答复用；当用户透露值得长期记住的事实或偏好时调用",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要记住的内容，一句话"}},
        "required": ["text"],
    },
)
def remember(args, user, db, cfg=None):
    text = (args.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "内容不能为空"}

    # 云端 embedding：工具在异步上下文中被同步调用，开新线程跑协程避免嵌套事件循环；
    # 失败静默降级为 None（记忆照常保存，召回端自动回退全量注入）
    import asyncio
    import concurrent.futures

    from ..agent.embed import embed_text, embedding_to_json
    from ..models import UserMemory

    def _embed():
        return asyncio.run(embed_text(text, cfg))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            embedding_json = embedding_to_json(pool.submit(_embed).result(timeout=20))
    except Exception:
        embedding_json = None

    m = UserMemory(user_id=user.id, content=text, embedding=embedding_json)
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"success": True, "id": m.id, "content": m.content}
