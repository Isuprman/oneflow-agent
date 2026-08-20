# OneFlow TTS 接口 — edge-tts（免费无 Key）
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/tts", tags=["tts"])

MAX_TEXT_LENGTH = 2000


class TtsRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"


@router.post("")
async def synthesize_tts(req: TtsRequest, user: User = Depends(get_current_user)) -> Response:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail="文本过长")

    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, req.voice)
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio_bytes += chunk["data"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"语音合成失败: {e}")

    return Response(content=audio_bytes, media_type="audio/mpeg")
