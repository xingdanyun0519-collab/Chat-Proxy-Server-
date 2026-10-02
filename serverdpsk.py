from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import json
import os
from datetime import datetime

app = FastAPI()

# ---------------------------------------------------------------------------
# Config / 配置
# ---------------------------------------------------------------------------

# Upstream API key. Leave empty here; set via env var UPSTREAM_API_KEY.
# 上游 API 密钥。此处留空，建议通过环境变量 UPSTREAM_API_KEY 设置。
API_KEY = os.getenv("UPSTREAM_API_KEY", "")

# Upstream chat completions endpoint / 上游接口地址
UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://api.deepseek.com/chat/completions")

# Model forced on every request / 强制使用的模型名
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash")

# Replacement text for the system prompt. Empty = no replacement.
# 用于替换 system 提示词的文本。留空则不替换。
REPLACEMENT_TEXT = os.getenv("REPLACEMENT_TEXT", "")

# Only system messages containing this marker are replaced.
# 仅替换包含该标记的 system 消息。
SYSTEM_MARKER = os.getenv("SYSTEM_MARKER", "<system_prompt>")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_IN_LOG = os.path.join(BASE_DIR, "game_in.log")      # raw client requests / 客户端原始请求
GAME_EDIT_LOG = os.path.join(BASE_DIR, "game_edit.log")  # edited requests / 修改后的请求
AI_REPLY_LOG = os.path.join(BASE_DIR, "ai_reply.log")    # upstream replies / 上游回复


# ---------------------------------------------------------------------------
# JSONL helpers / JSONL 读写工具
# One JSON object per line, newest last. 每行一个 JSON，最新的在最后。
# ---------------------------------------------------------------------------

def append_json_line(filepath: str, obj) -> None:
    """Append one JSON object as a line. / 追加一行 JSON。"""
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] Failed to write {filepath} / 写入失败: {e}")


def read_last_json_line(filepath: str):
    """Return the last line parsed as JSON, or None. / 返回最后一行的 JSON，失败返回 None。"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            chunk = b""
            # Scan backwards for the last non-empty line / 从末尾向前找最后一个非空行
            while pos > 0:
                pos -= 1
                f.seek(pos)
                byte = f.read(1)
                if byte == b"\n" and chunk.strip():
                    break
                chunk = byte + chunk
            last_line = chunk.decode("utf-8").strip()
        if not last_line:
            return None
        return json.loads(last_line)
    except Exception as e:
        print(f"[WARN] Failed to read {filepath} / 读取失败: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 1: system prompt replacement / 第一步：替换 system 提示词
# ---------------------------------------------------------------------------

def replace_system_content(data: dict) -> dict:
    """
    Replace the whole content of matching system messages with REPLACEMENT_TEXT.
    Does nothing if REPLACEMENT_TEXT is empty.
    整体替换匹配的 system 消息内容；REPLACEMENT_TEXT 为空时不做任何处理。
    """
    if not REPLACEMENT_TEXT:
        return data
    for msg in data.get("messages", []):
        if not isinstance(msg, dict) or msg.get("role") != "system":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and SYSTEM_MARKER in content:
            msg["content"] = REPLACEMENT_TEXT
    return data


# ---------------------------------------------------------------------------
# Step 2: response normalization / 第二步：响应格式归一化
# ---------------------------------------------------------------------------

def is_standard_chat_format(resp) -> bool:
    """
    Check for a standard chat.completion shape: non-empty choices,
    choices[0].message is a dict with a role. Empty content and tool_calls are valid.
    检查是否为标准 chat.completion 结构；空 content 和 tool_calls 均视为合法。
    """
    if not isinstance(resp, dict):
        return False
    choices = resp.get("choices")
    if not isinstance(choices, list) or len(choices) == 0:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return False
    return "role" in message


def wrap_into_standard_format(resp):
    """
    Extract whatever is usable from a non-standard response and wrap it
    in a standard chat.completion envelope.
    从非标准响应中尽量提取内容，封装成标准 chat.completion 格式。
    """
    content = ""
    tool_calls = None
    role = "assistant"
    finish_reason = "stop"

    if isinstance(resp, dict):
        if isinstance(resp.get("content"), str):
            content = resp.get("content")
        elif isinstance(resp.get("message"), dict):
            inner = resp["message"]
            content = inner.get("content") if isinstance(inner.get("content"), str) else ""
            tool_calls = inner.get("tool_calls")
            role = inner.get("role", role)
        elif isinstance(resp.get("choices"), list) and resp["choices"]:
            first = resp["choices"][0]
            if isinstance(first, dict):
                inner = first.get("message")
                if isinstance(inner, dict):
                    content = inner.get("content") if isinstance(inner.get("content"), str) else ""
                    tool_calls = inner.get("tool_calls")
                    role = inner.get("role", role)
                finish_reason = first.get("finish_reason", finish_reason)
        else:
            # Unknown shape: dump as string so the client still gets something.
            # 无法识别时转成字符串，保证客户端至少能拿到内容。
            content = json.dumps(resp, ensure_ascii=False)
    else:
        content = str(resp)

    message = {"role": role, "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": "local-normalized",
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": MODEL_NAME,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {},
    }


# ---------------------------------------------------------------------------
# Main flow / 主流程
# ---------------------------------------------------------------------------

async def call_upstream(client: httpx.AsyncClient, headers: dict, data: dict):
    """
    Forward the request upstream and return the JSON as-is.
    Returns None on network errors or invalid JSON.
    转发请求并原样返回 JSON；网络错误或非法 JSON 时返回 None。
    """
    try:
        response = await client.post(UPSTREAM_URL, headers=headers, json=data)
    except Exception as e:
        print(f"[ERROR] Upstream request failed / 请求上游失败: {e}")
        return None

    try:
        return response.json()
    except Exception:
        print(f"[WARN] Upstream returned invalid JSON, status={response.status_code} / "
              f"上游返回非法 JSON:\n{response.text[:500]}")
        return None


@app.post("/v1/chat/completions")
@app.post("/api/chat")
@app.post("/v1/api/chat")
async def chat_completions(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    # 1) Log raw client request / 记录客户端原始请求
    append_json_line(GAME_IN_LOG, data)

    # 2) Read it back (fallback to in-memory data) / 读回最后一行（失败则用内存数据）
    request_data = read_last_json_line(GAME_IN_LOG)
    if request_data is None:
        request_data = data

    request_data["model"] = MODEL_NAME
    request_data["stream"] = False

    # 3) Replace system prompt / 替换 system 提示词
    request_data = replace_system_content(request_data)

    # 4) Log edited request / 记录修改后的请求
    append_json_line(GAME_EDIT_LOG, request_data)

    # 5) Read it back and send upstream / 读回并发送给上游
    outgoing_data = read_last_json_line(GAME_EDIT_LOG)
    if outgoing_data is None:
        outgoing_data = request_data

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        upstream_response = await call_upstream(client, headers, outgoing_data)

    # 6) Log upstream reply as-is (None if invalid) / 原样记录上游回复（非法时记 None）
    append_json_line(AI_REPLY_LOG, upstream_response)

    # 7) Validate format; wrap if non-standard / 校验格式，非标准则封装
    final_response = read_last_json_line(AI_REPLY_LOG)

    if final_response is not None and is_standard_chat_format(final_response):
        response_to_game = final_response
    else:
        response_to_game = wrap_into_standard_format(final_response)

    return JSONResponse(
        content=response_to_game,
        media_type="application/json; charset=utf-8",
        status_code=200,
    )


@app.get("/")
async def root():
    return {"status": "server running"}
