# opencode 登录 OpenAI 报错排查（Unexpected server error）

日期：2026-08-24

## 问题

本机 `opencode auth login` 选择 OpenAI（ChatGPT Pro/Plus）时报错：

```
{"name":"UnknownError","data":{"message":"Unexpected server error. Check server logs for details.","ref":"err_e1f93c14"}}
```

## 原因

1. 日志位于 `%USERPROFILE%\.local\share\opencode\log\opencode.log`，真实错误为
   `Failed to initiate device authorization`。
2. 对应源码逻辑（`packages/opencode/src/plugin/openai/codex.ts`）：headless 登录会
   `POST https://auth.openai.com/api/accounts/deviceauth/usercode`，
   响应非 2xx 即抛该错误 —— 即**请求没到达/被墙**。
3. opencode 运行在 Bun 上，**不走 Windows 系统代理**（WinINET 设置的 `127.0.0.1:10808`
   只对 Invoke-WebRequest 等生效），只认 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量。

## 解决

写入用户级环境变量（新开的终端才生效）：

```powershell
[Environment]::SetEnvironmentVariable("HTTP_PROXY","http://127.0.0.1:10808","User")
[Environment]::SetEnvironmentVariable("HTTPS_PROXY","http://127.0.0.1:10808","User")
[Environment]::SetEnvironmentVariable("NO_PROXY","localhost,127.0.0.1,::1","User")
```

- `NO_PROXY` 排除 localhost，避免影响本地服务（如 sts2-ascend 的 8080 端口 API、Godot 等）。
- 之后重开终端执行 `opencode auth login` 即可成功。

## 注意事项

- 该变量对**所有**命令行工具生效（git/npm/dotnet 等），代理软件未开启时这些工具的外网请求都会失败；
  临时关闭可用 `$env:HTTP_PROXY=$null; $env:HTTPS_PROXY=$null`（仅当前会话）。
- 排查此类问题先看日志文件再定位真实异常，界面上的 ref 编码（如 err_xxx）只是引用 ID。
