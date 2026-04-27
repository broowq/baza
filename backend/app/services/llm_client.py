"""Unified LLM client — supports GigaChat (default, RU) and Anthropic Claude (fallback).

Provides a single `chat()` interface that returns the text response. Picks
provider based on settings.llm_provider.

Cost-cap awareness
──────────────────
When called with `organization_id`, every successful provider response is
priced (kopecks ₽×100) and added to the org's running monthly spend. If the
cap is already breached at call-entry time, the call is short-circuited
to None — same as a provider outage from the caller's perspective, so
downstream code transparently falls back to its rule-based path.

Token accounting:
  – Anthropic: `usage.input_tokens` / `usage.output_tokens` straight from
    the API. Prices come from settings (RUB per million tokens).
  – GigaChat: response carries `usage.prompt_tokens` / `completion_tokens`.
    If usage is missing (older SDK / mocked test), we estimate
    ceil(len_chars / 4) × 1 token as a conservative upper-bound.

Prices are kept in app.core.config so they're tunable per environment
(currency floats, model upgrades) without redeploying code.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_gigachat_client = None
_anthropic_client = None


# Kopecks per million tokens. These mirror real-world Apr 2026 pricing
# converted at ~83 ₽/$. Override via settings to keep code aligned with
# whatever the finance team negotiated.
_DEFAULT_PRICES_KOPECKS_PER_MTOK = {
    "anthropic_input": 25_000,    # claude-sonnet-4 input  ≈ $3 / 1M  → ₽250 / 1M  → 25_000 kopecks
    "anthropic_output": 125_000,  # claude-sonnet-4 output ≈ $15 / 1M → ₽1250 / 1M → 125_000 kopecks
    "gigachat_input":  500,       # GigaChat Lite input  ≈ ₽5 / 1M    → 500 kopecks
    "gigachat_output": 500,       # GigaChat Lite output ≈ ₽5 / 1M    → 500 kopecks
}


def _price_kopecks(provider: str, kind: str) -> int:
    """Look up price (kopecks per 1M tokens). Falls back to defaults."""
    settings = get_settings()
    overrides = getattr(settings, "llm_prices_kopecks_per_mtok", {}) or {}
    key = f"{provider}_{kind}"
    return int(overrides.get(key, _DEFAULT_PRICES_KOPECKS_PER_MTOK.get(key, 0)))


def _cost_kopecks(provider: str, input_tokens: int, output_tokens: int) -> int:
    """Total kopecks billed for a single LLM call. Always rounds UP — under-billing
    a customer is worse than over-billing by 1 kopeck per call."""
    in_price = _price_kopecks(provider, "input")
    out_price = _price_kopecks(provider, "output")
    raw = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return int(math.ceil(raw))


def _estimate_tokens(text: str) -> int:
    """Conservative upper-bound when the provider didn't report usage.
    GigaChat's tokenizer is roughly 1 token per 3-4 Cyrillic chars; we use 4
    so a missing-usage path slightly over-counts rather than slips free."""
    if not text:
        return 0
    return max(1, len(text) // 3)


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
    organization_id: Optional[str] = None,
) -> Optional[str]:
    """Send a chat message to the configured LLM provider.

    Returns the text response, or None on failure (provider outage,
    misconfigured credentials, OR org cost-cap hit).

    When `organization_id` is supplied:
      • Pre-flight: refuse if the org's monthly cap is already at/over.
      • Post-flight: charge the org by tokens × per-mtok price.
    Pass `organization_id=None` for system-level calls (CLI, admin tooling)
    that shouldn't be metered.

    Falls back from GigaChat to Anthropic automatically.
    """
    settings = get_settings()
    providers_to_try = (
        ["gigachat", "anthropic"]
        if settings.llm_provider == "gigachat"
        else ["anthropic", "gigachat"]
    )

    # Pre-flight cap check — short-circuits before we hit the network.
    if organization_id is not None:
        if not _has_budget(organization_id):
            logger.warning(
                "LLM call refused for org %s: monthly AI-cost cap reached",
                organization_id,
            )
            return None

    for provider in providers_to_try:
        try:
            if provider == "gigachat":
                result, in_tok, out_tok = _call_gigachat(user_message, system, max_tokens, temperature)
            else:
                result, in_tok, out_tok = _call_anthropic(user_message, system, max_tokens, temperature)
            if result:
                if organization_id is not None:
                    _charge(organization_id, provider, in_tok, out_tok)
                return result
        except Exception as e:
            logger.warning(f"LLM provider '{provider}' failed: {e}")
            continue

    return None


# ── Provider call wrappers — return (text, input_tokens, output_tokens) ─────

def _call_gigachat(
    user_message: str, system: str, max_tokens: int, temperature: float
) -> tuple[Optional[str], int, int]:
    client = _get_gigachat()
    if not client:
        return None, 0, 0

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
    text = response.choices[0].message.content if response.choices else None
    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", None) if usage else None
    out_tok = getattr(usage, "completion_tokens", None) if usage else None
    if in_tok is None:
        in_tok = _estimate_tokens(system) + _estimate_tokens(user_message)
    if out_tok is None:
        out_tok = _estimate_tokens(text or "")
    return text, int(in_tok), int(out_tok)


def _call_anthropic(
    user_message: str, system: str, max_tokens: int, temperature: float
) -> tuple[Optional[str], int, int]:
    client = _get_anthropic()
    if not client:
        return None, 0, 0

    kwargs = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    text = response.content[0].text if response.content else None
    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", None) if usage else None
    out_tok = getattr(usage, "output_tokens", None) if usage else None
    if in_tok is None:
        in_tok = _estimate_tokens(system) + _estimate_tokens(user_message)
    if out_tok is None:
        out_tok = _estimate_tokens(text or "")
    return text, int(in_tok), int(out_tok)


# ── Org-scoped cost accounting ─────────────────────────────────────────────

def _has_budget(organization_id: str) -> bool:
    """Cheap pre-flight: does this org still have any AI budget this month?

    Returns True when no row found (defensive — never starve an org due to a
    transient DB hiccup) and when the limit column is 0 (≡ unmetered).
    """
    try:
        from sqlalchemy import select
        from app.db.session import SessionLocal
        from app.models import Organization

        db = SessionLocal()
        try:
            org = db.execute(
                select(
                    Organization.ai_cost_used_kopecks_current_month,
                    Organization.ai_cost_limit_kopecks_per_month,
                ).where(Organization.id == organization_id)
            ).one_or_none()
            if not org:
                return True
            used, limit = org
            if (limit or 0) <= 0:
                # 0 = either unmetered (system orgs) or free-tier; the call
                # path is responsible for not invoking LLM for free-tier orgs.
                # We still allow here so legacy code paths keep working.
                return True
            return used < limit
        finally:
            db.close()
    except Exception:
        logger.exception("AI budget check failed — failing open")
        return True


def _charge(organization_id: str, provider: str, input_tokens: int, output_tokens: int) -> None:
    """Atomically increment the org's running monthly spend.

    Uses a single UPDATE … SET col = col + :delta so concurrent calls
    from celery workers can't lose increments. Fails silently on any DB
    error — losing accounting on one call is preferable to crashing the
    user's search.
    """
    cost = _cost_kopecks(provider, input_tokens, output_tokens)
    if cost <= 0:
        return
    try:
        from sqlalchemy import update
        from app.db.session import SessionLocal
        from app.models import Organization

        db = SessionLocal()
        try:
            db.execute(
                update(Organization)
                .where(Organization.id == organization_id)
                .values(
                    ai_cost_used_kopecks_current_month=(
                        Organization.ai_cost_used_kopecks_current_month + cost
                    )
                )
            )
            db.commit()
            logger.info(
                "AI charge: org=%s provider=%s in=%d out=%d cost=%d kop",
                organization_id, provider, input_tokens, output_tokens, cost,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        logger.exception("AI charge failed — call already completed, accounting skipped")


def is_configured() -> bool:
    """Check if at least one LLM provider is configured."""
    settings = get_settings()
    return bool(settings.gigachat_credentials) or bool(settings.anthropic_api_key)
