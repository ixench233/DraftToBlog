# DraftToBlog

DraftToBlog 是一个将 PDF、DOCX、Markdown 草稿整理为可发布内容的 Web 应用。前端使用 React，后端使用 Python FastAPI。

当前版本已经可以在不配置外部 API 的情况下完成：

- PDF、DOCX、Markdown 导入与文字解析；
- 手机号、邮箱、身份证号、IP 和常见内网地址扫描；
- 基础结构整理及逐项隐私替换；
- Markdown、DOCX、PDF 导出；
- 明亮/暗黑主题、演示文档和响应式工作台。

AI 内容优化、PicGo 上传和腾讯云 COS 会在填写 `.env` 后接入。当前界面会如实显示这些服务尚未配置。

## 目录

```text
backend/       FastAPI API、解析服务、导出服务与测试
frontend/      Vite + React + TypeScript 前端
design-system/ UI/UX Pro Max 生成的设计系统
```

## SiliconFlow AI

Set the following server-side values in the project-root `.env`:

```dotenv
OFFICIAL_AI_ENABLED=true
OFFICIAL_AI_BASE_URL=https://api.siliconflow.cn/v1
OFFICIAL_AI_API_KEY=your-api-key
OFFICIAL_AI_MODEL=your-model-id
OFFICIAL_AI_DAILY_REQUEST_LIMIT=100
OFFICIAL_AI_MAX_INPUT_CHARS=30000
OFFICIAL_AI_TIMEOUT_SECONDS=120
```

When **AI content optimization** is enabled, the processing endpoint masks the
selected sensitive values first and then sends the sanitized article to the
OpenAI-compatible API. If server AI is disabled, the application falls back to
local heading and whitespace normalization. A complete session-only API config
entered in the settings dialog takes precedence when `ALLOW_USER_AI_CONFIG=true`.

API keys stay on the server or are sent only in the processing request; they are
never returned by the configuration status endpoint.

## Image hosting

Embedded DOCX/PDF images are saved locally during analysis. After the user
chooses **Generate publishable version**, the backend invokes the configured
PicGo CLI with a temporary Tencent COS configuration assembled from `.env`.
The temporary file is deleted after the command finishes. If PicGo fails, the
backend falls back to the Tencent COS SDK. Successful public URLs are written
back to Markdown; DOCX and PDF exports download and embed those images.

Objects below `TENCENT_COS_PATH_PREFIX` older than
`TENCENT_COS_AUTO_DELETE_DAYS` are removed when the API starts. Set the value to
`0` to disable remote cleanup. The application dependency is
`cos-python-sdk-v5`; do not rely on a globally installed copy.

## Deployment configuration

`DEPLOY_*` values describe the deployment target and are reported as readiness
metadata. The web process never initiates SSH deployment, because allowing an
HTTP request to execute deployment credentials would be unsafe. Deployment is
performed separately after SSH authentication and the domain/SSL values are
configured.

## 本地启动

### 后端

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API 文档：http://127.0.0.1:8000/docs

### 前端

```powershell
cd frontend
npm install
npm run dev
```

应用地址：http://127.0.0.1:5173

## 配置

项目根目录的 `.env` 用于本机真实配置，该文件已被 Git 忽略。可提交的字段说明位于 `.env.example`。

在提供真实密钥前，至少需要确认以下配置：

- 官方测试 AI：Base URL、API Key、模型名称；
- 腾讯云 COS：SecretId、SecretKey、Bucket、Region、公开访问域名；
- PicGo：服务器上的可执行文件与配置文件路径；
- 云服务器：主机、SSH 用户、私钥路径、部署目录和域名。

不要把真实 Key 写入 `.env.example` 或前端源码。

## 验证命令

```powershell
cd backend
python -m pytest -q

cd ..\frontend
npm run lint
npm run build
npm audit --audit-level=moderate
```
