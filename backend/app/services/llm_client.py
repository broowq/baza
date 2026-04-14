"""Unified LLM client — supports GigaChat (default, RU) and Anthropic Claude (fallback).

Provides a single `chat()` interface that returns the text response.
Picks provider based on settings.llm_provider.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_gigachat_client = None
_anthropic_client = None


def _get_gigachat():
    global _gigachat_client
    if _gigachat_client is not None:
        return _gigachat_client
    settings = get_settings()
    if not settings.gigachat_credentials:
        return None
    try:
        from gigachat import GigaChat
        _gigachat_client = GigaChat(
            credentials=settings.gigachat_credentials,
            scope=settings.gigachat_scope,
            verify_ssl_certs=False,  # GigaChat uses custom Russian CA
            model=settings.gigachat_model,
        )
        return _gigachat_client
    except Exception as e:
        logger.warning(f"Failed to initialize GigaChat client: {e}")
        return None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
        kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        _anthropic_client = anthropic.Anthropic(**kwargs)
        return _anthropic_client
    except Exception as e:
        logger.warning(f"Failed to initialize Anthropic client: {e}")
        return None


def chat(
    user_message: str,
    *,
    system: str = "",
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> Optional[str]:
    """Send a chat message to the configured LLM provider.

    Returns the text response, or None on failure.
    Falls back from GigaChat to Anthropic automatically.
    """
    settings = get_settings()
    providers_to_try = []
    if settings.llm_provider == "gigachat":
        providers_to_try = ["gigachat", "anthropic"]
    else:
        providers_to_try = ["anthropic", "gigachat"]

    for provider in providers_to_try:
        try:
            if provider == "gigachat":
                result = _call_gigachat(user_message, system, max_tokens, temperature)
                if result:
                    return result
            elif provider == "anthropic":
                result = _call_anthropic(user_message, system, max_tokens, temperature)
                if result:
                    return result
        except Exception as e:
            logger.warning(f"LLM provider '{provider}' failed: {e}")
            continue

    return None


def _call_gigachat(user_message: str, system: str, max_tokens: int, temperature: float) -> Optional[str]:
    client = _get_gigachat()
    if not client:
        return None

    from gigachat.models import Chat, Messages, MessagesRole

    messages = []
    if system:
        messages.append(Messages(role=MessagesRole.SYSTEM, content=system))
    messages.append(Messages(role=MessagesRole.USER, content=user_message))

    response = client.chat(Chat(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    ))
    if response.choices:
        return response.choices[0].message.content
    return None


def _call_anthropic(user_message: str, system: str, max_tokens: int, temperature: float) -> Optional[str]:
    client = _get_anthropic()
    if not client:
        return None

    settings = get_settings()
    kwargs = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    if response.content:
        return response.content[0].text
    return None


def is_configured() -> bool:
    """Check if at least one LLM provider is configured."""
    settings = get_settings()
    return bool(settings.gigachat_credentials) or bool(settings.anthropic_api_key)
