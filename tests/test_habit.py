# 习惯学习测试 — 高频工具使用 → 主动建议通知，且不重复打扰
from datetime import datetime

from app.models import Conversation, Notification, ToolCallLog, User
from app.scheduler import run_habit_insights


def _seed(db, username, tool_name, times):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    for _ in range(times):
        db.add(
            ToolCallLog(
                conversation_id=conv.id,
                tool_name=tool_name,
                arguments="{}",
                result="{}",
                success=1,
            )
        )
    db.commit()
    return user


def test_habit_insight_suggests_frequent_tool(db_session):
    db = db_session()
    user = _seed(db, "habit_weather", "get_weather", 3)

    run_habit_insights(db, datetime.now())

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "habit"
    assert "天气" in notes[0].content
    db.close()


def test_habit_insight_below_threshold_silent(db_session):
    db = db_session()
    user = _seed(db, "habit_few", "get_weather", 2)  # 未达 3 次阈值

    run_habit_insights(db, datetime.now())

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
    db.close()


def test_habit_insight_not_repeated(db_session):
    db = db_session()
    user = _seed(db, "habit_dup", "add_expense", 5)
    now = datetime.now()

    run_habit_insights(db, now)
    run_habit_insights(db, now)  # 同一天第二次：habit_last_check 标记拦截

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    db.close()


def test_habit_insight_ignores_non_habit_tools(db_session):
    db = db_session()
    user = _seed(db, "habit_calc", "calculate", 10)  # 计算器不在洞察清单

    run_habit_insights(db, datetime.now())

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
    db.close()
