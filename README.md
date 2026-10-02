# Chat Proxy Server / 聊天中转服务器

A lightweight FastAPI proxy that sits between a client (e.g. a game) and an OpenAI-compatible chat API (default: DeepSeek).
一个轻量的 FastAPI 中转服务器，位于客户端（如游戏）与 OpenAI 兼容的聊天 API（默认 DeepSeek）之间。

## Features / 功能

- Forwards `chat/completions` requests to an upstream API / 转发请求到上游 API
- Forces a configurable model and disables streaming / 强制指定模型并关闭流式输出
- Optionally replaces the system prompt / 可选替换 system 提示词
- Normalizes non-standard upstream responses into the standard `chat.completion` format / 将非标准响应归一化为标准格式
- Logs requests and replies as JSONL / 以 JSONL 记录请求与回复

## Requirements / 环境要求

- Python 3.9+
- Packages / 依赖: `fastapi`, `uvicorn`, `httpx`

## Install / 安装

```bash
git clone <your-repo-url>
cd <your-repo>

# (Optional) virtual environment / 可选：虚拟环境
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install fastapi uvicorn httpx
```

## Configure / 配置

All settings are read from environment variables. / 所有配置通过环境变量设置。

| Variable | Default | Description / 说明 |
|---|---|---|
| `UPSTREAM_API_KEY` | *(empty)* | Upstream API key (required) / 上游 API 密钥（必填） |
| `UPSTREAM_URL` | `https://api.deepseek.com/chat/completions` | Upstream endpoint / 上游地址 |
| `MODEL_NAME` | `deepseek-v4-flash` | Model sent upstream / 发送给上游的模型名 |
| `REPLACEMENT_TEXT` | *(empty)* | Replaces matching system prompts; empty = off / 替换 system 提示词，留空则关闭 |
| `SYSTEM_MARKER` | `<system_prompt>` | Only system messages containing this are replaced / 仅替换包含此标记的消息 |

Linux / macOS:

```bash
export UPSTREAM_API_KEY="your-key-here"
```

Windows (PowerShell):

```powershell
$env:UPSTREAM_API_KEY = "your-key-here"
```

> **Never commit your API key.** / **切勿将 API 密钥提交到仓库。**

## Run / 运行

```bash
uvicorn serverdpsk:app --host 127.0.0.1 --port 8000
```

Check it works / 检查是否运行：

```bash
curl http://127.0.0.1:8000/
# {"status":"server running"}
```

## Endpoints / 接口

| Method | Path |
|---|---|
| POST | `/v1/chat/completions` |
| POST | `/api/chat` |
| POST | `/v1/api/chat` |
| GET | `/` (health check / 健康检查) |

Point your client's base URL to `http://127.0.0.1:8000` (use `0.0.0.0` as host to allow LAN access).
将客户端的接口地址指向 `http://127.0.0.1:8000`（如需局域网访问，host 改为 `0.0.0.0`）。

## Logs / 日志

Written next to the script, one JSON object per line / 保存在脚本同目录，每行一个 JSON：

- `game_in.log` — raw client requests / 客户端原始请求
- `game_edit.log` — requests after edits / 修改后的请求
- `ai_reply.log` — upstream replies / 上游回复

Logs may contain private conversation data and are excluded via `.gitignore`.
日志可能包含私人对话内容，已通过 `.gitignore` 排除。

## License / 许可证

Add a license of your choice (e.g. MIT). / 请自行添加许可证（如 MIT）。
