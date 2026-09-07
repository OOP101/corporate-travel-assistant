"""SSE 流式响应公共封装 (shared 模块)"""
import json

from fastapi.responses import StreamingResponse


def sse_frame(payload: dict) -> str:
    """把事件 dict 编码为一帧 SSE 文本（末尾带空行）"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


SSE_DONE = "data: [DONE]\n\n"


def sse_stream_response(generator) -> StreamingResponse:
    """把同步生成器包装为标准 SSE StreamingResponse。

    必须带 charset，否则调用方按 RFC 2616 回退 ISO-8859-1 解码会产出中文乱码。
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
