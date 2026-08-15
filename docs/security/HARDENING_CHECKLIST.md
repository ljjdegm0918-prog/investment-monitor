# 安全加固与生产上线清单（2026-08-15）

> 本文是安全审计（`docs/security/SECURITY_AUDIT_2026-08-15.md`）的落地清单。
> 只写配置要求与验证命令，**不写任何真实 token / 密码 / IP**。

## 已完成的代码加固

| 项 | 说明 |
|---|---|
| HIGH-01 鉴权 | `WEB_AUTH_TOKEN` 非空时，所有 `/api/*` 必须携带 `Authorization: Bearer <token>`，否则 401（code `web_auth_required`）；未设置时保持本机免鉴权兼容 |
| HIGH-03 extra_env | Settings 的 `extra_env:*` 改为白名单（`*_TIMEOUT_SECONDS` / `*_MAX_RETRIES` / `*_REQUESTS_PER_SECOND` / `*_LOOKBACK_DAYS` / `*_BACKFILL_DAYS`），含 `KEY/TOKEN/COOKIE/SECRET/PASSWORD/URL/VERIFY/SSL/AUTH/BEARER` 子串的名字一律 400 |
| HIGH-02 TLS 开关 | 由 extra_env 白名单覆盖：`*_VERIFY_SSL` 不再可能经 Web Settings 写入（.env / 进程环境仍可由运维手动设置，注意风险） |
| MED-04 响应头 | 全响应加 `X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`、基础 CSP（含 `frame-ancestors 'none'`） |
| MED-05 回填任务 | 终态任务内存保留最近 100 条；同时运行的回填线程最多 2 个，其余排队 |
| LOW-06 分页 | `/api/feed` 的 `page` 上限 1000，超限 400 |
| LOW-07 EDINET | EDINET 响应体 50MB 硬上限，Content-Length 过大或流式超限即失败 |

## 生产部署硬性要求

1. **监听隔离**：应用只监听 `127.0.0.1`（或容器只映射 `127.0.0.1:8765:8765`），由 Nginx/Caddy 终结 HTTPS 并反代。
2. **云安全组**：**禁止**对公网放行 `8765`（也不放行其它直连应用端口）。
3. **鉴权**：`.env` 设置强随机 `WEB_AUTH_TOKEN`（例如 `python -c "import secrets; print(secrets.token_urlsafe(32))"`），值只存在于服务器 `.env`，永不写入 git。
4. **同源校验**：`.env` 设置 `WEB_EXTERNAL_SCHEME=https`。
5. **反代**：nginx 示例（注意 `$http_host`）：

```nginx
server {
    listen 443 ssl;
    server_name <你的域名>;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

6. **浏览器 token**：部署后在浏览器控制台执行
   `localStorage.setItem("im_web_auth_token", "<WEB_AUTH_TOKEN 的值>")`，
   token 只存在浏览器 localStorage，不会写回服务端数据库。

## 部署后自检

```bash
# 1) 公网直连应用端口应不通（或非 200）
curl -m 5 -s -o /dev/null -w '%{http_code}\n' http://<服务器公网IP>:8765/api/settings || true

# 2) 经域名 HTTPS：无 token → API 401
curl -s -o /dev/null -w '%{http_code}\n' https://<你的域名>/api/settings

# 3) 带 token → 200
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer <WEB_AUTH_TOKEN>" \
  https://<你的域名>/api/settings

# 4) 响应头
curl -sI https://<你的域名>/ | grep -iE 'x-frame-options|x-content-type-options|content-security-policy'

# 5) extra_env 危险名必须 400（带同源 Origin 与 token）
curl -s -X POST https://<你的域名>/api/settings \
  -H "Content-Type: application/json" \
  -H "Origin: https://<你的域名>" \
  -H "Authorization: Bearer <WEB_AUTH_TOKEN>" \
  -d '{"key":"extra_env:RESEARCH_AI_BASE_URL","value":"https://evil.example"}'
# 期望：400
```

## 已知边界（保持原样，按审计结论不动）

- `*_VERIFY_SSL` 业务开关保留在代码中（CNMV 等上游有真实证书问题），只是无法再经 Web Settings 写入；运维改 `.env` 需自行评估 MITM 风险。
- 免费源诚实 stub 行为不变（审计 INFO-08 通过）。
- Settings 中 provider 密钥字段（正式产品功能）保留，仍以掩码显示。
