from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_markdown_workflow() -> None:
    content = "# 测试文章\n\n联系我：13812345678\n"
    response = client.post(
        "/api/documents/analyze",
        files={"file": ("draft.md", content.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_type"] == "markdown"
    assert payload["stats"]["findings"] == 1

    finding_id = payload["findings"][0]["id"]
    processed = client.post(
        f"/api/documents/{payload['id']}/process",
        json={"finding_ids": [finding_id], "improve_structure": True},
    )
    assert processed.status_code == 200
    assert "138****5678" in processed.json()["processed_content"]

    for format_name in ("markdown", "docx", "pdf"):
        exported = client.get(f"/api/documents/{payload['id']}/export/{format_name}")
        assert exported.status_code == 200
        assert exported.content


def test_rejects_unsupported_file() -> None:
    response = client.post(
        "/api/documents/analyze",
        files={"file": ("draft.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
