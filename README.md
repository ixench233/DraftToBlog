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
