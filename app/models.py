# OneFlow ORM 模型 —— 与 TRD §6 DDL 一致
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=now)

    expenses = relationship("Expense", back_populates="user", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSetting", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")
    scheduled_tasks = relationship("ScheduledTask", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255))
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCallLog", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)   # user / assistant / tool
    content = Column(Text)
    tool_call = Column(Text)                     # JSON
    reasoning_content = Column(Text)             # 思考模型(deepseek-reasoner 等)的思维链，多轮需原样回传
    created_at = Column(DateTime, default=now)

    conversation = relationship("Conversation", back_populates="messages")


class ToolCallLog(Base):
    __tablename__ = "tool_calls_log"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name = Column(String(64), nullable=False)
    arguments = Column(Text)                     # JSON
    result = Column(Text)                        # JSON
    success = Column(Integer, default=1)
    created_at = Column(DateTime, default=now)

    conversation = relationship("Conversation", back_populates="tool_calls")


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    category = Column(String(64))
    note = Column(Text)
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="expenses")


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime)
    notified = Column(Integer, default=0)        # 到期提醒是否已推送，防重复
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="schedules")


class ScheduledTask(Base):
    """用户定时任务：到点由调度器跑一遍 agent（可自动调工具）并主动播报。"""
    __tablename__ = "scheduled_tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255))
    instruction = Column(Text, nullable=False)    # 交给 agent 执行的指令，如"查今天天气并汇总今日日程"
    kind = Column(String(16), nullable=False)     # daily / weekly / once
    hour = Column(Integer, default=8)
    minute = Column(Integer, default=0)
    weekday = Column(Integer)                     # weekly 用：1=周一…7=周日
    run_at = Column(DateTime)                     # once 用的具体时刻
    enabled = Column(Integer, default=1)
    next_run_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="scheduled_tasks")


class Notification(Base):
    """主动播报/提醒：调度器产生，前端轮询拉取未读。"""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    kind = Column(String(16), default="task")     # task=定时任务播报 / reminder=日程提醒
    read = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="notifications")


class UserSetting(Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_setting"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(Text, default="")
    user = relationship("User", back_populates="settings")


class UserMemory(Base):
    __tablename__ = "user_memories"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Text)                     # JSON 向量（云端 embedding），语义召回用
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)
    user = relationship("User", back_populates="memories")


class UserProfile(Base):
    """结构化用户画像：城市/称呼等，供简报与播报做个性化上下文。"""
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_profile"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(Text, default="")


class CustomAgent(Base):
    """用户自定义子智能体：人设 + 工具白名单，delegate 动态路由。"""
    __tablename__ = "custom_agents"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(32), nullable=False)
    persona = Column(Text, nullable=False)
    tools = Column(Text, nullable=False)         # JSON 数组：允许的工具名
    created_at = Column(DateTime, default=now)


class PendingAction(Base):
    """高危操作待确认：engine 遇到需确认工具时暂存，等用户确认后再执行。"""
    __tablename__ = "pending_actions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(64), nullable=False)
    arguments = Column(Text, nullable=False)     # JSON
    summary = Column(Text, nullable=False)       # 给用户看的确认描述
    created_at = Column(DateTime, default=now)
