from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services import media_service


def test_unreachable_public_url_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")

    monkeypatch.setattr(
        media_service,
        "settings",
        SimpleNamespace(temp_dir=Path(""), cos_ready=False, picgo_ready=True),
    )
    monkeypatch.setattr(media_service, "_upload_picgo", lambda path: "https://cdn.example.com/missing.png")

    def failed_get(*args, **kwargs):
        request = httpx.Request("GET", "https://cdn.example.com/missing.png")
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError("bad gateway", request=request, response=response)

    monkeypatch.setattr(media_service.httpx, "head", failed_get)

    asset = {"filename": "image.png", "local_path": str(image), "status": "pending", "url": "", "provider": "", "error": ""}
    media_service._upload_one_asset("", asset)

    assert asset["status"] == "failed"
    assert "public URL is not reachable" in asset["error"]


def test_public_url_check_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    request = httpx.Request("HEAD", "https://cdn.example.com/image.png")

    def flaky_head(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectError("temporary tls eof", request=request)
        return httpx.Response(200, headers={"content-type": "image/png"}, request=request)

    monkeypatch.setattr(media_service.httpx, "head", flaky_head)
    monkeypatch.setattr(media_service.time, "sleep", lambda seconds: None)

    media_service._ensure_public_url_available("https://cdn.example.com/image.png")

    assert attempts["count"] == 3


def test_upload_provider_retries_connection_aborted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    attempts = {"count": 0}

    def flaky_upload(provider: str, path: Path) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionAbortedError(10053, "connection aborted")
        return "https://cdn.example.com/image.png"

    monkeypatch.setattr(media_service, "_upload_with_provider", flaky_upload)
    monkeypatch.setattr(media_service.time, "sleep", lambda seconds: None)

    assert media_service._upload_with_provider_with_retries("cos", image) == "https://cdn.example.com/image.png"
    assert attempts["count"] == 3


def test_auto_provider_falls_back_to_picgo_when_cos_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")

    monkeypatch.setattr(
        media_service,
        "settings",
        SimpleNamespace(
            temp_dir=tmp_path,
            upload_provider="auto",
            cos_ready=True,
            picgo_ready=True,
            cos_upload_workers=1,
        ),
    )
    monkeypatch.setattr(media_service, "_ensure_public_url_available", lambda url: None)

    def upload(provider: str, path: Path) -> str:
        if provider == "cos":
            raise ConnectionAbortedError(10053, "connection aborted")
        return "https://cdn.example.com/image.png"

    monkeypatch.setattr(media_service, "_upload_with_provider_with_retries", upload)

    asset = {"filename": "image.png", "local_path": "image.png", "status": "pending", "url": "", "provider": "", "error": ""}
    media_service._upload_one_asset("", asset)

    assert asset["status"] == "uploaded"
    assert asset["provider"] == "picgo"


def test_remote_provider_is_selected_when_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        media_service,
        "settings",
        SimpleNamespace(upload_provider="remote", remote_upload_ready=True),
    )

    assert media_service._upload_provider_order() == ["remote"]


def test_remote_public_url_check_accepts_image_response() -> None:
    class FakeClient:
        pass

    stdout = "HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"

    def fake_exec(*args, **kwargs):
        return stdout, "", 0

    original = media_service._remote_exec
    media_service._remote_exec = fake_exec
    try:
        media_service._ensure_remote_public_url_available(FakeClient(), "https://cdn.example.com/image.png")
    finally:
        media_service._remote_exec = original
