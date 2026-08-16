from fastapi.testclient import TestClient

from app.main import app
from app.services import document_service
from app.services.ai_service import (
    AIConnection,
    AIServiceError,
    _build_rewrite_prompt,
    _is_mostly_chinese,
    _protect_image_markers,
    _restore_missing_image_markers,
    _unprotect_image_markers,
)

import pytest


client = TestClient(app)


@pytest.fixture(autouse=True)
def stub_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    client.post("/api/auth/login", json={"username": "demo_user", "password": "123456"})
    monkeypatch.setattr(
        document_service,
        "upload_task_assets",
        lambda task_id, assets: assets,
    )


def test_official_ai_failure_falls_back_to_local_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_service,
        "resolve_connection",
        lambda ai_config=None: AIConnection(
            base_url="https://api.example.com/v1",
            api_key="server-key",
            model="server-model",
            uses_official_quota=True,
        ),
    )
    monkeypatch.setattr(
        document_service,
        "improve_article",
        lambda *args, **kwargs: (_ for _ in ()).throw(AIServiceError("AI API Key invalid")),
    )
    analyzed = client.post(
        "/api/documents/analyze",
        files={"file": ("fallback.md", "# 标题\n\n正文".encode(), "text/markdown")},
    ).json()
    response = client.post(
        f"/api/documents/{analyzed['id']}/process",
        json={"finding_ids": [], "improve_structure": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processed"
    assert "服务器 AI 配置暂不可用" in "".join(payload["warnings"])


def test_image_markers_are_protected_and_restored_near_original_context() -> None:
    original = "第一段介绍\n\n[IMG_0]\n\n第二段解释图表\n\n[IMG_1]\n\n第三段结论"
    protected = _protect_image_markers(original)
    assert "@@DTBIMAGE0:" in protected
    assert _unprotect_image_markers(protected) == original

    rewritten_without_markers = "第一段介绍已经优化。\n\n第二段解释图表，说明趋势。\n\n第三段结论。"
    restored = _restore_missing_image_markers(original, rewritten_without_markers)
    assert "[IMG_0]" in restored
    assert "[IMG_1]" in restored
    assert restored.index("[IMG_0]") < restored.index("第二段解释图表")
    assert restored.index("[IMG_1]") < restored.index("第三段结论")


def test_image_captions_are_bound_to_protected_markers() -> None:
    original = "写作框架\n\n示例图 1\n\n[IMG_0]\n\n示例图 2\n\n[IMG_1]\n\n示例图 3\n\n[IMG_2]\n\n摘要页写作"
    protected = _protect_image_markers(original)
    assert "@@DTBIMAGE0:" in protected
    assert "@@DTBIMAGE1:" in protected
    assert "@@DTBIMAGE2:" in protected

    restored = _unprotect_image_markers(protected)
    assert "示例图 1\n\n[IMG_0]" in restored
    assert "示例图 2\n\n[IMG_1]" in restored
    assert "示例图 3\n\n[IMG_2]" in restored


def test_restore_missing_image_markers_restores_captions() -> None:
    original = "\u5199\u4f5c\u6846\u67b6\n\n\u793a\u4f8b\u56fe 1\n\n[IMG_0]\n\n\u793a\u4f8b\u56fe 2\n\n[IMG_1]\n\n\u6458\u8981\u9875\u5199\u4f5c"
    rewritten = "\u5199\u4f5c\u6846\u67b6\n\n\u8fd9\u91cc\u662f\u4f18\u5316\u540e\u7684\u5199\u4f5c\u6846\u67b6\u5185\u5bb9\u3002\n\n\u6458\u8981\u9875\u5199\u4f5c"

    restored = _restore_missing_image_markers(original, rewritten)

    assert "\u793a\u4f8b\u56fe 1\n\n[IMG_0]" in restored
    assert "\u793a\u4f8b\u56fe 2\n\n[IMG_1]" in restored


def test_chinese_draft_prompt_requires_chinese_output() -> None:
    text = "这是一篇中文博客，介绍 TypeScript 和 Vue 项目搭建流程。"
    assert _is_mostly_chinese(text)
    prompt = _build_rewrite_prompt(text, "frontend.md", True)
    assert "必须使用中文输出" in prompt
    assert "不要翻译成英文" in prompt


def test_chinese_prompt_requires_image_anchor_preservation() -> None:
    prompt = _build_rewrite_prompt("@@DTBIMAGE8:@@", "images.md", True)

    assert "@@DTBIMAGE" in prompt
    assert "不要移动到文末" in prompt


def test_ai_rewrite_falls_back_when_image_order_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ai_service
    from app.services.ai_service import AIConnection, improve_article

    def fake_call(*args, **kwargs):
        return "正文 B\n\n@@DTBIMAGE1:@@\n\n正文 A\n\n@@DTBIMAGE0:@@"

    monkeypatch.setattr(ai_service, "_call_chat", fake_call)

    result = improve_article(
        "正文 A\n\n[IMG_0]\n\n正文 B\n\n[IMG_1]",
        "images.md",
        AIConnection(base_url="https://api.example.com", api_key="key", model="model"),
    )

    assert result.index("[IMG_0]") < result.index("[IMG_1]")


def test_ai_rewrite_preserves_image_order_without_dropping_rewritten_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ai_service
    from app.services.ai_service import AIConnection, improve_article

    calls: list[str] = []

    def fake_call(connection, system_prompt, user_prompt, max_tokens, stage):
        calls.append(stage)
        if len(calls) == 1:
            return (
                "\u7b2c\u4e8c\u6bb5\u88ab AI \u6539\u5199\u4e86\n\n"
                "@@DTBIMAGE1:@@\n\n"
                "\u7b2c\u4e00\u6bb5\u88ab AI \u6539\u5199\u4e86\n\n"
                "@@DTBIMAGE0:@@"
            )
        return f"{stage} \u4f18\u5316\u540e\u7684\u6b63\u6587"

    monkeypatch.setattr(ai_service, "_call_chat", fake_call)

    result = improve_article(
        (
            "\u7b2c\u4e00\u6bb5\u539f\u59cb\u6b63\u6587\uff0c\u8fd9\u91cc\u9700\u8981\u4fdd\u6301\u56fe\u7247\u524d\u7684\u4e0a\u4e0b\u6587\uff0c"
            "\u4f46\u662f\u6587\u5b57\u672c\u8eab\u5e94\u8be5\u7ee7\u7eed\u88ab AI \u4f18\u5316\u3002\n\n"
            "[IMG_0]\n\n"
            "\u7b2c\u4e8c\u6bb5\u539f\u59cb\u6b63\u6587\uff0c\u5b83\u5728\u7b2c\u4e00\u5f20\u56fe\u540e\u9762\uff0c\u4e5f\u8981\u88ab\u6539\u5199\uff0c"
            "\u4f46\u4e0d\u80fd\u628a\u7b2c\u4e8c\u5f20\u56fe\u63d0\u524d\u6216\u8005\u653e\u5230\u672b\u5c3e\u3002\n\n"
            "[IMG_1]"
        ),
        "images.md",
        AIConnection(base_url="https://api.example.com", api_key="key", model="model"),
    )

    assert result.index("[IMG_0]") < result.index("[IMG_1]")
    assert "\u4f18\u5316\u540e\u7684\u6b63\u6587" in result
    assert "\u7b2c\u4e00\u6bb5\u539f\u59cb\u6b63\u6587" not in result
    assert len(calls) == 3


def test_processed_document_keeps_uploaded_images_near_original_context(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = document_service.analyze_upload(
        "images.md",
        "第一段介绍\n\n[IMG_0]\n\n第二段解释图表\n\n[IMG_1]\n\n第三段结论".encode(),
    )
    payload["assets"] = [
        {
            "filename": "image-1.png",
            "local_path": "assets/image-1.png",
            "status": "uploaded",
            "url": "https://cdn.example.com/1.png",
            "provider": "cos",
            "error": "",
        },
        {
            "filename": "image-2.png",
            "local_path": "assets/image-2.png",
            "status": "uploaded",
            "url": "https://cdn.example.com/2.png",
            "provider": "cos",
            "error": "",
        },
    ]
    monkeypatch.setattr(document_service.store, "get", lambda task_id: payload if task_id == payload["id"] else None)
    monkeypatch.setattr(document_service.store, "update", lambda task_id, payload: None)
    monkeypatch.setattr(
        document_service,
        "resolve_connection",
        lambda ai_config=None: AIConnection(
            base_url="https://api.example.com/v1",
            api_key="server-key",
            model="server-model",
        ),
    )
    monkeypatch.setattr(
        document_service,
        "improve_article",
        lambda *args, **kwargs: "第一段介绍已经优化。\n\n第二段解释图表，说明趋势。\n\n第三段结论。",
    )

    processed = document_service.process_document(
        payload["id"],
        finding_ids=[],
        improve_structure=True,
    )
    content = processed["processed_content"]
    assert "https://cdn.example.com/1.png" in content
    assert "https://cdn.example.com/2.png" in content
    assert content.index("https://cdn.example.com/1.png") < content.index("第二段解释图表")
    assert content.index("https://cdn.example.com/2.png") < content.index("第三段结论")
