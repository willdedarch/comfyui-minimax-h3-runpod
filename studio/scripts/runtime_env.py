"""Shared, non-secret download settings; apply before importing Hugging Face."""
from __future__ import annotations

import os


def default_environment(root):
    """Return literal paths: Runpod environment values do not expand $variables."""
    cache = root / ".cache" / "huggingface"
    return {
        "HF_HOME": str(cache),
        "HF_HUB_CACHE": str(cache / "hub"),
        "HF_XET_CACHE": str(cache / "xet"),
        "HF_ASSETS_CACHE": str(cache / "assets"),
        "HF_XET_HIGH_PERFORMANCE": "1",
        "HF_XET_CHUNK_CACHE_SIZE_BYTES": "0",
        "HF_HUB_DOWNLOAD_TIMEOUT": "120",
        "HF_HUB_ETAG_TIMEOUT": "30",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }


def configure_environment(root):
    """Preserve explicit overrides and never read, persist, or return credentials."""
    defaults = default_environment(root)
    # A custom HF_HOME also supplies the defaults of its child caches.
    hf_home = os.environ.get("HF_HOME") or defaults["HF_HOME"]
    defaults.update({
        "HF_HOME": hf_home,
        "HF_HUB_CACHE": hf_home.rstrip("/\\") + "/hub",
        "HF_XET_CACHE": hf_home.rstrip("/\\") + "/xet",
        "HF_ASSETS_CACHE": hf_home.rstrip("/\\") + "/assets",
    })
    for key, value in defaults.items():
        if not os.environ.get(key):
            os.environ[key] = value
    for key in ("HF_HUB_DOWNLOAD_TIMEOUT", "HF_HUB_ETAG_TIMEOUT"):
        try:
            if int(os.environ[key]) <= 0:
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} must contain a positive number of seconds") from None
