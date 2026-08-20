# add_expense / query_expense — 记账，真实 SQLite 持久化
from ..models import Expense
from .registry import tool


@tool(
    name="add_expense",
    description="记一笔支出",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "金额，必须大于 0"},
            "category": {"type": "string", "description": "分类，如餐饮/交通"},
            "note": {"type": "string", "description": "备注"},
        },
        "required": ["amount"],
    },
    requires_confirm=True,
)
def add_expense(args, user, db):
    amount = args.get("amount")
    if amount is None:
        return {"success": False, "error": "缺少金额"}
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"success": False, "error": "金额格式错误"}
    if amount <= 0:
        return {"success": False, "error": "金额必须大于 0"}

    exp = Expense(user_id=user.id, amount=amount, category=args.get("category"), note=args.get("note"))
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return {
        "success": True,
        "id": exp.id,
        "amount": exp.amount,
        "category": exp.category,
        "note": exp.note,
    }


@tool(
    name="query_expense",
    description="查询当前用户的支出记录（可按月份、分类过滤）",
    parameters={
        "type": "object",
        "properties": {
            "month": {"type": "string", "description": "YYYY-MM，可选"},
            "category": {"type": "string", "description": "分类，精确匹配"},
        },
    },
)
def query_expense(args, user, db):
    month = args.get("month")
    category = args.get("category")
    q = db.query(Expense).filter(Expense.user_id == user.id)
    if month:
        q = q.filter(Expense.created_at.like(month + "%"))
    if category:
        q = q.filter(Expense.category == category)
    items = q.order_by(Expense.created_at.desc()).all()

    return {
        "success": True,
        "total": round(sum(e.amount for e in items), 2),
        "count": len(items),
        "items": [
            {
                "amount": e.amount,
                "category": e.category,
                "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in items
        ],
    }
