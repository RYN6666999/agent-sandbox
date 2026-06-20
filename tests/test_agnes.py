"""Tests for Agnes multimodal module and API endpoints."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


# ── mock fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_litellm():
    """Mock litellm to prevent real API calls in all tests."""
    with patch("orchestrator.agnes.litellm") as mock:
        yield mock


def _mock_choice(text: str):
    """Build a fake litellm response choice."""
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    return choice


# ── orchestrator/agnes.py — analyze_image ─────────────────────────────────


def test_analyze_image_with_url(mock_litellm):
    """圖片 URL → 回傳分析文字。"""
    from orchestrator.agnes import analyze_image

    mock_resp = MagicMock()
    mock_resp.choices = [_mock_choice("A red apple on a table.")]
    mock_litellm.completion.return_value = mock_resp

    result = analyze_image(image_url="https://example.com/apple.jpg")
    assert result["analysis"] == "A red apple on a table."
    assert "error" not in result
    assert result["model"] != ""


def test_analyze_image_with_base64(mock_litellm):
    """Base64 編碼 → 回傳分析文字。"""
    from orchestrator.agnes import analyze_image

    mock_resp = MagicMock()
    mock_resp.choices = [_mock_choice("A cat.")]
    mock_litellm.completion.return_value = mock_resp

    b64 = "data:image/jpeg;base64,/9j/4AAQ=="
    result = analyze_image(image_base64=b64)
    assert result["analysis"] == "A cat."


def test_analyze_image_with_custom_prompt(mock_litellm):
    """自訂 prompt → 傳入 content。"""
    from orchestrator.agnes import analyze_image

    mock_resp = MagicMock()
    mock_resp.choices = [_mock_choice("Contains text: Hello")]
    mock_litellm.completion.return_value = mock_resp

    result = analyze_image(
        image_url="https://example.com/sign.jpg",
        prompt="Read the text in this image.",
    )
    assert "Hello" in result["analysis"]


def test_analyze_image_no_source(mock_litellm):
    """無 image_url 也無 image_base64 → error。"""
    from orchestrator.agnes import analyze_image

    result = analyze_image()
    assert result["analysis"] == ""
    assert "error" in result
    mock_litellm.completion.assert_not_called()


def test_analyze_image_error(mock_litellm):
    """litellm 拋錯 → error。"""
    from orchestrator.agnes import analyze_image

    mock_litellm.completion.side_effect = RuntimeError("API timeout")

    result = analyze_image(image_url="https://example.com/x.jpg")
    assert result["analysis"] == ""
    assert "error" in result


# ── orchestrator/agnes.py — generate_image ────────────────────────────────


def test_generate_image_success(mock_litellm):
    """產圖成功 → 回傳 URL。"""
    from orchestrator.agnes import generate_image

    mock_resp = MagicMock()
    mock_data = MagicMock()
    mock_data.url = "https://agnes-ai.com/image/abc123.png"
    mock_resp.data = [mock_data]
    mock_litellm.image_generation.return_value = mock_resp

    result = generate_image(prompt="a cute cat")
    assert result["url"] == "https://agnes-ai.com/image/abc123.png"
    assert result["prompt"] == "a cute cat"
    assert "error" not in result


def test_generate_image_empty_prompt(mock_litellm):
    """空 prompt → error。"""
    from orchestrator.agnes import generate_image

    result = generate_image(prompt="")
    assert result["url"] == ""
    assert "error" in result
    mock_litellm.image_generation.assert_not_called()


def test_generate_image_error(mock_litellm):
    """litellm 拋錯 → error。"""
    from orchestrator.agnes import generate_image

    mock_litellm.image_generation.side_effect = RuntimeError("gen failed")

    result = generate_image(prompt="sunset")
    assert result["url"] == ""
    assert "error" in result


# ── orchestrator/agnes.py — generate_video ────────────────────────────────


def test_generate_video_success(mock_litellm):
    """送 video 任務 → 回傳 task_id。"""
    from orchestrator.agnes import generate_video

    mock_resp = MagicMock()
    mock_resp.data = [MagicMock()]
    mock_litellm.image_generation.return_value = mock_resp

    result = generate_video(prompt="a flying bird")
    assert result["status"] == "submitted"
    assert "task_id" in result


def test_generate_video_empty_prompt(mock_litellm):
    """空 prompt → error。"""
    from orchestrator.agnes import generate_video

    result = generate_video(prompt="")
    assert result["status"] == "error"
    assert "error" in result
    mock_litellm.image_generation.assert_not_called()


# ── orchestrator/agnes.py — get_video_status ──────────────────────────────


@patch("orchestrator.agnes.urllib.request.urlopen")
def test_video_status_completed(mock_urlopen):
    """video status → completed。"""
    from orchestrator.agnes import get_video_status

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status":"completed","url":"https://agnes-ai.com/video/abc.mp4"}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    result = get_video_status(task_id="task_123")
    assert result["status"] == "completed"
    assert result["url"] == "https://agnes-ai.com/video/abc.mp4"


@patch("orchestrator.agnes.urllib.request.urlopen")
def test_video_status_pending(mock_urlopen):
    """video status → pending。"""
    from orchestrator.agnes import get_video_status

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status":"processing"}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    result = get_video_status(task_id="task_123")
    assert result["status"] == "processing"


@patch("orchestrator.agnes.urllib.request.urlopen")
def test_video_status_error(mock_urlopen):
    """video status → error。"""
    from orchestrator.agnes import get_video_status

    mock_urlopen.side_effect = RuntimeError("connection failed")

    result = get_video_status(task_id="task_123")
    assert result["status"] == "error"
    assert "error" in result


def test_video_status_empty_id():
    """空 task_id → error。"""
    from orchestrator.agnes import get_video_status

    result = get_video_status(task_id="")
    assert result["status"] == "error"
    assert "error" in result


# ── POST /vision/analyze API ──────────────────────────────────────────────


@patch("orchestrator.agnes.litellm")
def test_vision_api_success(mock_llm):
    """POST /vision/analyze → 回傳分析。"""
    mock_resp = MagicMock()
    mock_resp.choices = [_mock_choice("A dog.")]
    mock_llm.completion.return_value = mock_resp

    r = client.post("/vision/analyze", json={
        "image_url": "https://example.com/dog.jpg",
        "prompt": "What animal?",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["analysis"] == "A dog."


@patch("orchestrator.agnes.litellm")
def test_vision_api_no_image(mock_llm):
    """無圖片來源 → error。"""
    r = client.post("/vision/analyze", json={"prompt": "desc"})
    assert r.status_code == 200
    assert r.json()["analysis"] == ""
    assert "error" in r.json()


# ── POST /image/generate API ──────────────────────────────────────────────


@patch("orchestrator.agnes.litellm")
def test_image_api_success(mock_llm):
    """POST /image/generate → 回傳 url。"""
    mock_resp = MagicMock()
    mock_data = MagicMock()
    mock_data.url = "https://agnes-ai.com/img/xyz.png"
    mock_resp.data = [mock_data]
    mock_llm.image_generation.return_value = mock_resp

    r = client.post("/image/generate", json={"prompt": "sunset", "size": "1024x1024"})
    assert r.status_code == 200
    assert r.json()["url"] == "https://agnes-ai.com/img/xyz.png"


# ── POST /video/generate API ──────────────────────────────────────────────


@patch("orchestrator.agnes.litellm")
def test_video_api_submit(mock_llm):
    """POST /video/generate → 回傳 task_id。"""
    mock_resp = MagicMock()
    mock_resp.data = [MagicMock()]
    mock_llm.image_generation.return_value = mock_resp

    r = client.post("/video/generate", json={"prompt": "flying eagle"})
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"


# ── GET /video/status API ─────────────────────────────────────────────────


@patch("orchestrator.agnes.urllib.request.urlopen")
def test_video_status_api(mock_urlopen):
    """GET /video/status/{id} → polling。"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status":"completed","url":"https://agnes-ai.com/v/abc.mp4"}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    r = client.get("/video/status/task_123")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# ── /executors lists agnes-* ──────────────────────────────────────────────


def test_executors_includes_agnes():
    """GET /executors → 包含 agnes-analyze / agnes-image / agnes-video。"""
    r = client.get("/executors")
    names = [e["name"] for e in r.json()["executors"]]
    assert "agnes-analyze" in names
    assert "agnes-image" in names
    assert "agnes-video" in names
    assert "web-search" in names  # 確認前次遺失已修復