"""Agnes multimodal — vision analysis, image generation, video generation.

Wraps litellm calls to Agnes models (agnes-2.0-flash, agnes-image-2.1-flash, agnes-video-v2.0).
All functions take raw params and return dicts — no Pydantic, no framework coupling.
"""

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import litellm

from orchestrator.model_registry import resolve as resolve_model

VIDEO_POLL_INTERVAL = 3  # seconds between status checks
VIDEO_MAX_POLL = 60  # max polls before timeout


# ── helpers ───────────────────────────────────────────────────────────────


def _resolve(alias: str) -> dict:
    """Resolve model alias, return litellm kwargs."""
    return resolve_model(alias)


def _model_name(alias: str) -> str:
    """Extract model string from alias."""
    return _resolve(alias).get("model", alias)


def _agentes_base() -> str:
    """Get Agnes API base URL."""
    return os.environ.get(
        "AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1"
    )


def _agentes_key() -> str:
    """Get Agnes API key."""
    return os.environ.get("AGNES_API_KEY", "")


# ── vision / analyze ──────────────────────────────────────────────────────


def analyze_image(
    image_url: str | None = None,
    image_base64: str | None = None,
    prompt: str = "Describe this image in detail.",
) -> dict[str, Any]:
    """Analyze an image using Agnes vision model.

    Args:
        image_url: Public URL of the image.
        image_base64: Base64-encoded image data (data:image/...;base64,...).
        prompt: Text prompt for the analysis.

    Returns:
        dict with keys: analysis (str), model (str), error (str, optional).
    """
    if not image_url and not image_base64:
        return {"analysis": "", "model": "", "error": "image_url or image_base64 required"}

    content = []
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    if image_base64:
        content.append({"type": "image_url", "image_url": {"url": image_base64}})
    content.append({"type": "text", "text": prompt})

    params = _resolve("agnes")
    try:
        resp = litellm.completion(
            messages=[{"role": "user", "content": content}],
            max_tokens=1024,
            temperature=0.3,
            **params,
        )
        text = resp.choices[0].message.content.strip()
        return {"analysis": text, "model": params.get("model", "")}
    except Exception as e:
        return {"analysis": "", "model": params.get("model", ""), "error": str(e)}


# ── image generation ──────────────────────────────────────────────────────


def generate_image(
    prompt: str,
    size: str = "1024x1024",
    n: int = 1,
) -> dict[str, Any]:
    """Generate an image using Agnes image model.

    Args:
        prompt: Text description of the image.
        size: Image size (e.g. "1024x1024", "1920x1080").
        n: Number of images to generate.

    Returns:
        dict with keys: url (str), prompt (str), model (str), error (str, optional).
    """
    if not prompt.strip():
        return {"url": "", "prompt": "", "model": "", "error": "prompt required"}

    params = _resolve("agnes-image")
    try:
        resp = litellm.image_generation(
            prompt=prompt,
            n=n,
            size=size,
            **params,
        )
        url = resp.data[0].url if resp.data else ""
        return {"url": url, "prompt": prompt, "model": params.get("model", "")}
    except Exception as e:
        return {"url": "", "prompt": prompt, "model": params.get("model", ""), "error": str(e)}


# ── video generation (async, polling-based) ───────────────────────────────


def generate_video(prompt: str) -> dict[str, Any]:
    """Submit a video generation task.

    Agnes video API is async. Returns a task_id for polling.

    Args:
        prompt: Text description of the video.

    Returns:
        dict with keys: task_id (str), status (str), prompt (str), error (str, optional).
    """
    if not prompt.strip():
        return {"task_id": "", "status": "error", "prompt": "", "error": "prompt required"}

    params = _resolve("agnes-video")
    api_base = params.get("api_base", _agentes_base())
    api_key = params.get("api_key", _agentes_key())

    try:
        # litellm video generation usually returns a task reference
        resp = litellm.image_generation(
            prompt=prompt,
            model=params.get("model", "openai/agnes-video-v2.0"),
            api_key=api_key,
            api_base=api_base,
        )
        # litellm response may have task_id in different places
        raw = getattr(resp, "raw", None) or {}
        task_id = (
            raw.get("id")
            or raw.get("task_id")
            or getattr(resp, "task_id", "")
        )
        return {
            "task_id": task_id or "pending",
            "status": "submitted",
            "prompt": prompt,
        }
    except Exception as e:
        # Fallback: try direct HTTP call if litellm fails
        try:
            return _direct_video_submit(prompt, api_base, api_key)
        except Exception as e2:
            return {
                "task_id": "", "status": "error",
                "prompt": prompt,
                "error": f"litellm: {e}; direct: {e2}",
            }


def _direct_video_submit(
    prompt: str, api_base: str, api_key: str
) -> dict[str, Any]:
    """Fallback: POST directly to Agnes video endpoint."""
    url = f"{api_base.rstrip('/')}/video/generations"
    payload = json.dumps({
        "model": "agnes-video-v2.0",
        "prompt": prompt,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    task_id = data.get("id") or data.get("task_id") or ""
    return {
        "task_id": task_id,
        "status": "submitted",
        "prompt": prompt,
    }


def get_video_status(task_id: str) -> dict[str, Any]:
    """Poll video generation status.

    Args:
        task_id: Task ID from generate_video().

    Returns:
        dict with keys: status (str), url (str, optional), error (str, optional).
    """
    if not task_id:
        return {"status": "error", "error": "task_id required"}

    params = _resolve("agnes-video")
    api_base = params.get("api_base", _agentes_base())
    api_key = params.get("api_key", _agentes_key())
    url = f"{api_base.rstrip('/')}/video/status/{task_id}"

    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        status = data.get("status", "unknown")
        result = {"status": status, "task_id": task_id}
        if data.get("url"):
            result["url"] = data["url"]
        if data.get("error"):
            result["error"] = data["error"]
        return result
    except Exception as e:
        return {"status": "error", "task_id": task_id, "error": str(e)}


def wait_for_video(
    task_id: str, poll_interval: int = VIDEO_POLL_INTERVAL, max_polls: int = VIDEO_MAX_POLL
) -> dict[str, Any]:
    """Block until video generation completes or times out."""
    for _ in range(max_polls):
        result = get_video_status(task_id)
        if result["status"] in ("completed", "error", "failed"):
            return result
        time.sleep(poll_interval)
    return {"status": "timeout", "task_id": task_id, "error": "poll limit reached"}
