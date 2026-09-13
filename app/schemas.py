# OneFlow Pydantic schemas
from typing import Optional, List

from pydantic import BaseModel, Field


# ---------- 认证 ----------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- 会话 ----------
class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationOut(BaseModel):
    id: int
    title: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    role: str
    content: Optional[str]

    class Config:
        from_attributes = True


# ---------- 工具轨迹 ----------
class ToolStep(BaseModel):
    tool: str
    arguments: dict
    result: dict
    success: bool = True


# ---------- 聊天 ----------
class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    steps: int
    trace: List[ToolStep] = []


class HealthOut(BaseModel):
    status: str
    llm_provider: str
    llm_model: str


# ---------- 每用户配置 ----------
class LlmConfigIn(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


class LlmConfigOut(BaseModel):
    provider: str
    model: str
    api_key_set: bool = False     # 是否已设置（不回传真实密钥）
    base_url: str = ""
    configured: bool = False      # 用户已配 或 全局已配


class HotelConfigIn(BaseModel):
    base_url: str = ""
    api_key: str = ""


class HotelConfigOut(BaseModel):
    base_url: str = ""
    api_key_set: bool = False
    configured: bool = False


# ---------- 长期记忆 ----------
class MemoryOut(BaseModel):
    id: int
    content: str
    created_at: str

    class Config:
        from_attributes = True


class MemoryUpdate(BaseModel):
    content: str


# ---------- 主动通知（定时任务播报/日程提醒） ----------
class NotificationOut(BaseModel):
    id: int
    title: str
    content: str
    kind: str
    created_at: str

    class Config:
        from_attributes = True
