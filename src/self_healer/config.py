"""
self_healer.config
==================
Centralised configuration — all settings are read from environment variables.

Users set these env vars before running pytest:
    GROQ_API_KEY          — Required. Your Groq API key.
    GROQ_BASE_URL         — Optional. Defaults to Groq's OpenAI-compatible endpoint.
    SELF_HEAL_MODEL       — Optional. LLM model name. Defaults to llama-3.3-70b-versatile.
    SELF_HEAL_TEMPERATURE — Optional. LLM temperature (0.0–1.0). Defaults to 0.4.
"""

import os


def _get_required(name: str) -> str:
    """Return an env var or raise a helpful error."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"[self-healer] Environment variable '{name}' is not set. "
            f"Please export it before running your tests."
        )
    return val


def get_api_key() -> str:
    return _get_required("GROQ_API_KEY")


def get_base_url() -> str:
    return os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


def get_model_name() -> str:
    return os.environ.get("SELF_HEAL_MODEL", "llama-3.3-70b-versatile")


def get_temperature() -> float:
    return float(os.environ.get("SELF_HEAL_TEMPERATURE", "0.4"))
