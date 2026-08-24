# HumanLLM 安全加固清单 (Security Hardening)

> 本次升级目标：**防爆破、防滥用、防令牌盗用、收紧默认配置**。
> 所有新增能力均可通过环境变量开关，**默认开启**（除 HSTS 需显式 `FORCE_HSTS=true`）。

## 1. 登录防爆破 (Anti-Brute-Force)

| 防护 | 实现 | 配置 |
|---|---|---|
| 每 IP 登录频率限制 | `RateLimiter` 滑动窗口，1 分钟内超过阈值直接 429 | `RATE_LOGIN_PER_MIN=10` |
| 账号+IP 累积锁入 | 连续失败累积计数，达阈值后账号与 IP 双双锁定时长 | `LOGIN_MAX_FAIL=5` / `LOGIN_LOCKOUT_SECONDS=900` |
| 通用错误响应 | 无论用户名是否存在、密码是否正确，统一返回 `400 Invalid credentials`，不泄露账号是否存在 | 既有 |
| 登录审计 | 每次成功/失败/限流/锁入均写入 `EventLog`（`auth.login.*`） | 既有 + 增强 |

文件：`app/auth_guard.py`（失败计数 + 锁入 + 审计）、`app/routers/worker_auth.py`（登录路由接入）、`app/ratelimit.py`（限流器）。

## 2. 令牌可吊销 (Token Revocation)

- `users` 表新增 `token_version INTEGER NOT NULL DEFAULT 0`（`migrations/0006_token_version.sql`）。
- 登录签发的 JWT 携带 `tv` 声明与 `iss=humanllm`。
- `app/deps.py` 在 `get_current_user` / 仪表盘用户 WS 鉴权时校验 `payload.tv == user.token_version`。
- **效果**：修改密码 → `token_version` 自增 → 此前签发的所有 JWT 立即失效（返回 `401 Token revoked`），实现强制重新登录。
- 额外加固：JWT 校验增加签发方 (`iss`) 校验，伪造/非本服务签发的令牌一律拒绝。

## 3. 密码强度策略 (Password Policy)

`app/security.py::validate_password_strength`：

- 最小长度 `PASSWORD_MIN_LENGTH=12`
- 大小写 + 数字（特殊字符可选 `PASSWORD_REQUIRE_SPECIAL`）
- 拦截常见弱密码（`password`、`123456`、`admin`、`qwerty` 等）
- 应用于：管理员后台**创建用户**与**修改密码**接口（`app/routers/admin.py`）

## 4. 限流 (Rate Limiting)

| 层 | 范围 | 默认 | 开关 |
|---|---|---|---|
| 全局按 IP | 所有路由（除 `/health`、`/assets`、`/favicon`） | 600/分钟 | `RATE_LIMIT_ENABLED` → `RATE_GLOBAL_PER_MIN` |
| 登录按 IP | `/auth/login` | 10/分钟 | 同上 |
| API Key 按 Key | `/v1/chat/completions` | 60/分钟 | 同上 |

实现：`app/ratelimit.py`（进程内滑动窗口，零依赖；多 worker/多机可换 Redis）。

## 5. 安全响应头 (Security Headers)

`app/middleware.py::SecurityHeadersMiddleware`（默认开启，`SECURITY_HEADERS_ENABLED=true`）：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`（防点击劫持）
- `Referrer-Policy: no-referrer`
- `Permissions-Policy`（禁用 geolocation/microphone/camera/payment/usb）
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy`（同源脚本/样式，阻断 framing，`frame-ancestors 'none'`）
- 剥离 `Server` / `X-Powered-By` 指纹头
- `Strict-Transport-Security`（仅 `FORCE_HSTS=true` 且 HTTPS 部署时下发）

## 6. 请求体大小限制 (Body Size Guard)

- `BodySizeLimitMiddleware`：POST/PUT/PATCH 超 `MAX_BODY_BYTES`（默认 25MB）直接 `413`。
- chat 内联附件（图片/文件 data URL）上限 `MAX_INLINE_BYTES`（默认 10MB），超出返回 `400`。

## 7. CORS 收紧 (CORS Hardening)

- 默认不再通配 `*` + `allow_credentials=True`（该组合浏览器无效且不安全）。
- `STRICT_CORS=true`（默认）下，若 `CORS_ORIGINS` 仍含 `*`，自动**关闭凭据**并告警。
- 生产环境请在 `.env` 显式设置 `CORS_ORIGINS=https://your-frontend.com`。

## 8. 启动保护 (Startup Guard)

- `JWT_SECRET` 仍为开发占位符时：非 DEBUG 且 `JWT_REQUIRE_SECRET=true` → **直接拒绝启动**；否则生成临时密钥并告警（重启后旧令牌失效，提醒立即配置）。
- 生产务必设置 `JWT_SECRET`（≥32 字节随机串）与 `JWT_REQUIRE_SECRET=true`。

## 9. 既有基础（保留）

bcrypt 密码哈希、JWT (HS256)、API Key (sha256 存储)、RBAC（super_admin / staff + 细粒度权限）、登录通用错误、审计日志表。

## 部署检查清单

```bash
# 必改项（.env）
JWT_SECRET=<openssl rand -hex 32>        # 32+ 字节随机
JWT_REQUIRE_SECRET=true
CORS_ORIGINS=https://your-frontend.com   # 不要留 *
FORCE_HSTS=true                          # 仅当走 HTTPS
RATE_LIMIT_ENABLED=true
```

## 验证记录

- ✅ 登录成功 / 失败通用错误
- ✅ 单 IP 10 次/分钟后 429
- ✅ 连续 5 次失败 → 账号+IP 锁入 15 分钟
- ✅ 改密码后旧 JWT 立即 401（吊销）
- ✅ 弱密码创建/修改被 400 拦截
- ✅ 安全响应头全部下发，Server 头已剥离
- ✅ 启动保护：占位密钥 + 非 DEBUG + REQUIRE=true 拒绝启动

> 说明：项目自带 pytest 套件中有 4 失败 / 6 错误，均为**陈旧测试**（引用了未播种的演示 API Key `sk-humanllm-demo-key-0001`、不存在的 `/api/auth/worker/register` 路由、期望 `worker1` 用户名），与本次安全升级无关，属升级前既有问题。如需我顺手修测试可另开任务。
