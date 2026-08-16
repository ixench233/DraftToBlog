from app.services import ai_service
from app.services.ai_service import AIConnection, AIServiceError, improve_article


def test_long_article_uses_plan_rewrite_and_merge(monkeypatch) -> None:
    calls: list[str] = []

    def fake_call(connection, system_prompt, user_prompt, max_tokens, stage):
        if "制定一份博客文章整理规划" in user_prompt:
            calls.append("plan")
            return "主标题：测试文章\n章节：背景、方法、结论"
        if "当前片段" in user_prompt:
            calls.append("rewrite")
            return "## 背景\n\n内容\n\n![IMG_0](draft-to-blog://IMG_0)"
        if "统一合并" in user_prompt:
            calls.append("merge")
            return "# 测试文章\n\n## 背景\n\n内容\n\n![IMG_0](draft-to-blog://IMG_0)"
        raise AssertionError(user_prompt)

    monkeypatch.setattr(ai_service, "_call_chat", fake_call)
    text = "中文内容。" * 1000 + "\n\n[IMG_0]\n\n" + "更多内容。" * 1000
    result = improve_article(
        text,
        "draft.md",
        AIConnection(base_url="https://api.example.com/v1", api_key="key", model="model"),
    )
    assert calls[0] == "plan"
    assert calls[-1] == "merge"
    assert calls.count("rewrite") > 1
    assert "[IMG_0]" in result


def test_merge_failure_keeps_rewritten_chunks(monkeypatch) -> None:
    calls: list[str] = []

    def fake_call(connection, system_prompt, user_prompt, max_tokens, stage):
        if stage == "全文规划":
            calls.append("plan")
            return "主标题：测试文章\n章节：背景、结论"
        if stage.startswith("分块改写"):
            calls.append("rewrite")
            return "## 已改写片段\n\n这是 AI 改写后的内容。\n\n![IMG_0](draft-to-blog://IMG_0)"
        if stage == "统一合并":
            calls.append("merge")
            raise AIServiceError("AI 服务在「统一合并」阶段返回格式异常")
        raise AssertionError(stage)

    monkeypatch.setattr(ai_service, "_call_chat", fake_call)
    text = "中文内容。" * 1000 + "\n\n[IMG_0]\n\n" + "更多内容。" * 1000
    result = improve_article(
        text,
        "draft.md",
        AIConnection(base_url="https://api.example.com/v1", api_key="key", model="model"),
    )
    assert calls[-1] == "merge"
    assert "这是 AI 改写后的内容" in result
    assert "[IMG_0]" in result


def test_large_rewritten_article_uses_local_merge(monkeypatch) -> None:
    calls: list[str] = []

    def fake_call(connection, system_prompt, user_prompt, max_tokens, stage):
        calls.append(stage)
        if stage == "全文规划":
            return "主标题：测试文章\n章节：背景、结论"
        if stage.startswith("分块改写"):
            return ("## 已改写片段\n\n这是 AI 改写后的内容。\n\n" + "内容" * 1500 + "\n\n![IMG_0](draft-to-blog://IMG_0)")
        raise AssertionError(f"large article should not call merge: {stage}")

    monkeypatch.setattr(ai_service, "_call_chat", fake_call)
    text = "中文内容。" * 1000 + "\n\n[IMG_0]\n\n" + "更多内容。" * 1000
    result = improve_article(
        text,
        "draft.md",
        AIConnection(base_url="https://api.example.com/v1", api_key="key", model="model"),
    )
    assert "统一合并" not in calls
    assert "这是 AI 改写后的内容" in result
    assert "[IMG_0]" in result
