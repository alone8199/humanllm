# HumanLLM API 参考

所有接口的基础路径：`http://<host>:<port>`（默认后端 `8000`）。OpenAI 兼容接口挂载在 `/v1` 下。本文档中的 `Authorization: Bearer <token>` 既接受 **API Key**（`sk-...`，调用方用），也接受 **Worker/Admin JWT**（工作台与管理后台用）。

> 核心约束：**没有任何 AI**。所有回复均来自真人 Worker。

---

## 1. OpenAI 兼容接口（调用方）

### `GET /v1/models`
列出可用模型（需 API Key）。

**响应**
```json
{
  "object": "list",
  "data": [
    {
      "id": "human-default",
      "object": "model",
      "owned_by": "humanllm",
      "display_name": "Human Default",
      "description": "A general-purpose human answers your prompt.",
      "pricing": {
        "per_request_cents": 5,
        "per_1k_chars_cents": 1,
        "per_minute_cents": 10,
        "concurrency": 2,
        "timeout_seconds": 600
      }
    }
  ]
}
```

### `POST /v1/chat/completions`
创建一次"补全"请求（创建任务 → 分配真人 → 真人回复 → 返回）。需 API Key。

**请求体**
```json
{
  "model": "human-default",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user",   "content": "用一句话介绍 HumanLLM。"}
  ],
  "stream": false,
  "stream_options": {"include_usage": true}
}
```

多模态消息示例（图片 / 文件 / data URL）：
```json
{
  "model": "human-default",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "描述这张图。"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}},
        {"type": "file_url",  "file_url":  {"url": "https://example.com/doc.pdf"}}
      ]
    }
  ],
  "stream": true
}
```

**非流式响应（200）**
```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "human-default",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "<真人回复>"}, "finish_reason": "stop"}
  ],
  "usage": {"prompt_tokens": 12, "completion_tokens": 24, "total_tokens": 36}
}
```

**流式响应（SSE，`stream: true`）**
```
data: {"id":"chatcmpl-<uuid>","object":"chat.completion.chunk","created":1700000000,"model":"human-default","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"choices":[{"index":0,"delta":{"content":"你"},"finish_reason":null}]}

data: {"choices":[{"index":0,"delta":{"content":"的问题是"},"finish_reason":null}]}

data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{...}}

data: [DONE]
```

**错误（OpenAI 格式）**
```json
{
  "error": {
    "message": "The model 'x' does not exist or is not available.",
    "type": "invalid_request_error",
    "code": "model_not_found"
  }
}
```
常见错误码：`401 authentication_error`（缺/错 Key）、`402 insufficient_quota`（余额不足）、`404 model_not_found`、`504 timeout`、`409 cancelled`、`500 worker_error`。

---

## 2. 文件接口（调用方）

### `POST /v1/files`
上传文件（multipart，`file` 字段）。支持图片与文档（PDF/TXT/JSON/CSV/DOCX/XLSX）。

**响应**
```json
{"id": 1, "filename": "doc.pdf", "content_type": "application/pdf", "size": 1234, "url": "/v1/files/content/<key>", "storage_key": "<key>"}
```

### `GET /v1/files`
列出已上传文件。

### `GET /v1/files/content/{key}`
下载/预览文件二进制（API Key / Admin / Worker 任一身份可访问）。

---

## 3. 鉴权接口

### `POST /auth/worker/register`
```json
{"username": "alice", "password": "pw", "skills": ["cn","pdf"], "display_name": "Alice"}
```
→ `{"access_token": "<jwt>", "token_type": "bearer"}`

### `POST /auth/worker/login`
```json
{"username": "worker1", "password": "worker123"}
```
→ `{"access_token": "<jwt>", "token_type": "bearer"}`

### `POST /auth/admin/login`
```json
{"username": "admin", "password": "admin123"}
```
→ `{"access_token": "<jwt>", "token_type": "bearer"}`

### `GET /auth/user/apikeys`
列出当前调用方用户的 API Key（需调用方 JWT）。

---

## 4. Worker 工作台接口（需 Worker JWT）

### `GET /worker/me`
→ `{id, username, display_name, status, skills, earnings_cents, current_task_id, served_models}`

### `GET /worker/tasks`
→ `{pending: [{id, model, status, preview}], active: {id, model, status} | null}`

### `WS /ws/worker?token=<jwt>`
实时通道。服务端 → Worker：
```jsonc
{"type": "task_assigned", "task": {
  "id": "<uuid>", "model": "human-default",
  "messages": [{"role":"system","content":"..."}, {"role":"user","content":[...]}],
  "stream": true, "created_at": "2024-...",
  "attachments": [{"id":1,"kind":"image","url":"...","filename":"a.png","content_type":"image/png"}]
}}

{"type": "new_task", "task_id": "<uuid>", "model": "human-default"}  // grab 模式通知
{"type": "pong"}                                                                 // 心跳回应
{"type": "error", "message": "..."}
```

Worker → 服务端：
```jsonc
{"type": "heartbeat"}
{"type": "grab",   "task_id": "<uuid>"}                 // 认领 pending 任务
{"type": "chunk",  "task_id": "<uuid>", "text": "..."}  // 流式回复片段
{"type": "done",   "task_id": "<uuid>", "text": "<完整回复>"}  // 提交最终回复
{"type": "cancel", "task_id": "<uuid>"}
```

---

## 5. 管理员接口（需 Admin JWT）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/admin/stats`     | 概览统计（用户/Worker/模型/任务数、平台收入等） |
| GET  | `/admin/users`     | 用户列表 |
| GET  | `/admin/workers`   | Worker 列表（含状态、收入） |
| GET  | `/admin/models`    | 模型列表 |
| POST | `/admin/models`    | 新建模型 `{name, display_name, description, price_per_request_cents, price_per_1k_chars_cents, price_per_minute_cents, concurrency, timeout_seconds, worker_usernames:[]}` |
| GET  | `/admin/apikeys`   | API Key 列表 |
| GET  | `/admin/tasks`     | 任务列表（含状态、模型、分配情况） |
| GET  | `/admin/usage`     | 用量 / 交易记录 |
| GET  | `/admin/logs`      | 事件日志 |

---

## 6. 健康检查

### `GET /health`
→ `{"status":"ok","service":"humanllm"}`

### `GET /`
→ 服务信息。
