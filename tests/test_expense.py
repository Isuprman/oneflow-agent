# add_expense / query_expense 测试 — 使用 conftest 临时库
from app.models import User
from app.tools.expense import add_expense, query_expense


def _make_user(db):
    user = User(username="expense-tester", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_expense_add_and_summary(db_session):
    db = db_session()
    user = _make_user(db)

    r1 = add_expense({"amount": 100, "category": "food", "note": "午餐"}, user, db)
    r2 = add_expense({"amount": 50, "category": "transport", "note": "打车"}, user, db)
    assert r1["success"] is True and r1["amount"] == 100
    assert r2["success"] is True and r2["id"] is not None

    summary = query_expense({}, user, db)
    assert summary["success"] is True
    assert summary["count"] == 2
    assert summary["total"] == 150
    amounts = {item["amount"] for item in summary["items"]}
    assert amounts == {100, 50}


def test_expense_filter_by_category(db_session):
    db = db_session()
    user = _make_user(db)

    add_expense({"amount": 100, "category": "food"}, user, db)
    add_expense({"amount": 50, "category": "transport"}, user, db)

    by_cat = query_expense({"category": "food"}, user, db)
    assert by_cat["success"] is True
    assert by_cat["count"] == 1
    assert by_cat["total"] == 100
    assert by_cat["items"][0]["category"] == "food"


def test_expense_filter_by_month(db_session):
    from datetime import datetime

    db = db_session()
    user = _make_user(db)

    add_expense({"amount": 10, "category": "food"}, user, db)
    month = datetime.now().strftime("%Y-%m")
    by_month = query_expense({"month": month}, user, db)
    assert by_month["success"] is True
    assert by_month["count"] == 1


def test_add_expense_invalid_amount(db_session):
    db = db_session()
    user = _make_user(db)

    result = add_expense({"amount": -5}, user, db)
    assert result["success"] is False
    assert "大于 0" in result["error"]
