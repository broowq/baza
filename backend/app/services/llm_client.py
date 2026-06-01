"""Unified LLM client — supports YandexGPT (default, RU), GigaChat (RU fallback)
and Anthropic Claude (overseas fallback).

Provides a single `chat()` interface that returns the text response. Picks
the primary provider from settings.llm_provider and cascades through the
others on failure.

Cost-cap awareness
──────────────────
When called with `organization_id`, every successful provider response is
priced (kopecks ₽×100) and added to the org's running monthly spend. If the
cap is already breached at call-entry time, the call is short-circuited
to None — same as a provider outage from the caller's perspective, so
downstream code transparently falls back to its rule-based path.

Token accounting:
  – YandexGPT: response.result.usage.{inputTextTokens,completionTokens} from
    the REST API. Strings → ints (Yandex returns numerics as strings).
  – Anthropic: usage.input_tokens / usage.output_tokens from the SDK.
  – GigaChat:  usage.prompt_tokens / completion_tokens from the SDK.
  – If usage is missing (older SDK / mocked test) we estimate
    ceil(len_chars / 3) so a missing-usage path slightly over-counts
    rather than slips free.

Prices live in _DEFAULT_PRICES_KOPECKS_PER_MTOK; override via
settings.llm_prices_kopecks_per_mtok if finance retunes them later.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_gigachat_client = None
_anthropic_client = None


# Kopecks per million tokens. May 2026 published rates (sync mode, with VAT)
# from https://aistudio.yandex.ru/docs/ru/ai-studio/pricing.html and Sber/Anthropic
# public pages. Override via settings.llm_prices_kopecks_per_mtok if finance
# negotiated a different tariff.
#
# Reference YandexGPT sync prices (₽/1K → kopecks/1M):
#   yandexgpt-lite/latest    : ₽0.20  →   20_000  ← our default
#   gpt-oss-20b/latest       : ₽0.10  →   10_000  ← 2× cheaper, same arch
#   gpt-oss-120b/latest      : ₽0.30  →   30_000
#   qwen3-35b (sync)         : ₽0.20 in / ₽0.30 out
#   yandexgpt/rc  (Pro 5.1)  : ₽0.80  →   80_000
#   yandexgpt/latest (Pro 5) : ₽1.20  →  120_000
# Async mode (where supported) is ~50% of sync — see Yandex pricing docs.
_DEFAULT_PRICES_KOPECKS_PER_MTOK = {
    # Anthropic Claude Sonnet
    "anthropic_input": 25_000,    # ≈ $3 / 1M  → ₽250  / 1M  → 25_000 kopecks
    "anthropic_output": 125_000,  # ≈ $15 / 1M → ₽1250 / 1M  → 125_000 kopecks
    # GigaChat Lite (Sber)
    "gigachat_input":  500,       # ≈ ₽5 / 1M
    "gigachat_output": 500,
    # YandexGPT Lite (Yandex AI Studio) — current code default
    "yandex_input":  20_000,
    "yandex_output": 20_000,
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
    RU tokenizers are roughly 1 token per 3-4 Cyrillic chars; we use 3
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

    Provider cascade is built from settings.llm_provider as the head, then
    the remaining two configured providers in deterministic order. So with
    `llm_provider=yandex` the chain is yandex → anthropic → gigachat; with
    `llm_provider=gigachat` it's gigachat → yandex → anthropic; etc.
    """
    settings = get_settings()
    primary = (settings.llm_provider or "yandex").lower()
    rotation = {
        "yandex":   ["yandex", "anthropic", "gigachat"],
        "anthropic":["anthropic", "yandex", "gigachat"],
        "gigachat": ["gigachat", "yandex", "anthropic"],
    }
    providers_to_try = rotation.get(primary, rotation["yandex"])

    # ── 152-ФЗ guard ────────────────────────────────────────────────
    # Strip out-of-RF providers when foreign-transfer is not authorised
    # (default). This is the single hardest line in the codebase to bypass
    # accidentally: even if ANTHROPIC_API_KEY is set in env, the provider
    # is never tried unless settings.llm_allow_foreign_providers is True.
    if not getattr(settings, "llm_allow_foreign_providers", False):
        foreign = {"anthropic"}
        providers_to_try = [p for p in providers_to_try if p not in foreign]
        if primary in foreign:
            logger.warning(
                "Primary provider %r is out-of-RF but "
                "LLM_ALLOW_FOREIGN_PROVIDERS=false; falling back to in-RF chain",
                primary,
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
            if provider == "yandex":
                result, in_tok, out_tok = _call_yandex(user_message, system, max_tokens, temperature)
            elif provider == "gigachat":
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

def _call_yandex(
    user_message: str, system: str, max_tokens: int, temperature: float
) -> tuple[Optional[str], int, int]:
    """Call YandexGPT via Yandex Cloud Foundation Models REST API.

    Auth: Api-Key in Authorization header. Folder ID is part of the modelUri
    (gpt://<folder>/<model>) and Yandex doesn't accept the call without it.

    No third-party SDK — the REST surface is small and adding `yandex-cloud-ml-sdk`
    would pull >40 transitive deps for one POST. httpx is already in the stack.
    """
    settings = get_settings()
    if not settings.yandex_gpt_api_key or not settings.yandex_gpt_folder_id:
        return None, 0, 0

    messages = []
    if system:
        messages.append({"role": "system", "text": system})
    messages.append({"role": "user", "text": user_message})

    payload = {
        "modelUri": f"gpt://{settings.yandex_gpt_folder_id}/{settings.yandex_gpt_model}",
        "completionOptions": {
            "stream": False,
            "temperature": float(temperature),
            "maxTokens": str(int(max_tokens)),
        },
        "messages": messages,
    }
    headers = {
        "Authorization": f"Api-Key {settings.yandex_gpt_api_key}",
        "Content-Type": "application/json",
        # x-folder-id is technically redundant when folder is in modelUri, but
        # Yandex docs recommend setting both for tracing/quota observability.
        "x-folder-id": settings.yandex_gpt_folder_id,
    }

    # 60s — enough room for a max-tokens=2500 completion plus network jitter,
    # but still bounded so one slow upstream doesn't lock a celery worker.
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(settings.yandex_gpt_endpoint, json=payload, headers=headers)

    if resp.status_code >= 400:
        # Surface auth/quota errors loudly so ops alerts can pick them up
        # (mirrors the GigaChat error envelope handling).
        body = resp.text[:300]
        logger.warning(
            "YandexGPT HTTP %s: %s", resp.status_code, body,
        )
        return None, 0, 0

    data = resp.json()
    result = data.get("result") or {}
    alternatives = result.get("alternatives") or []
    text: Optional[str] = None
    if alternatives:
        msg = alternatives[0].get("message") or {}
        text = msg.get("text") or None

    usage = result.get("usage") or {}
    # Yandex returns numeric fields as STRINGS in JSON ("47" not 47).
    in_tok = _safe_int(usage.get("inputTextTokens"))
    out_tok = _safe_int(usage.get("completionTokens"))
    if in_tok is None:
        in_tok = _estimate_tokens(system) + _estimate_tokens(user_message)
    if out_tok is None:
        out_tok = _estimate_tokens(text or "")

    return text, int(in_tok), int(out_tok)


def _safe_int(value) -> Optional[int]:
    """Yandex usage fields are JSON strings; coerce defensively."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    # FIX (Bug #4): temperature was previously omitted, making Anthropic calls
    # non-deterministic (API default = 1.0).  Pass it through so the filter
    # gets the same low-temperature (0.1) behaviour as YandexGPT/GigaChat.
    kwargs = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "temperature": float(temperature),
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
    """Check if at least one LLM provider is ACTUALLY usable at runtime.

    FIX (Bug #3): The previous implementation returned True whenever any API
    key was set — including Anthropic-only configurations. However, the 152-FZ
    guard in chat() strips Anthropic from the provider list at runtime unless
    LLM_ALLOW_FOREIGN_PROVIDERS=true, so the filter would attempt an AI call,
    receive None back for every batch, and silently fall through to rule-based
    without the caller (or the log) making it obvious why.

    Now: we check the same filtering logic that chat() uses, so is_configured()
    returns True only when at least one provider that will actually be tried at
    runtime has its credentials set.  A clear WARNING is emitted when keys are
    present but all effective providers are blocked so ops can diagnose it.
    """
    settings = get_settings()
    allow_foreign = getattr(settings, "llm_allow_foreign_providers", False)
    foreign_providers = {"anthropic"}

    has_yandex    = bool(settings.yandex_gpt_api_key and settings.yandex_gpt_folder_id)
    has_gigachat  = bool(settings.gigachat_credentials)
    has_anthropic = bool(settings.anthropic_api_key)

    # Build the set of providers that chat() will actually attempt.
    effective: list[str] = []
    if has_yandex:
        effective.append("yandex")
    if has_gigachat:
        effective.append("gigachat")
    if has_anthropic:
        effective.append("anthropic")

    if not allow_foreign:
        effective = [p for p in effective if p not in foreign_providers]

    if effective:
        return True

    # No usable provider at runtime — emit a diagnostic warning so the silence
    # is visible in logs/Sentry rather than looking like a normal rule-based run.
    configured_keys = []
    if has_yandex:
        configured_keys.append("yandex")
    if has_gigachat:
        configured_keys.append("gigachat")
    if has_anthropic:
        configured_keys.append("anthropic (blocked by 152-FZ guard)")
    if configured_keys:
        logger.warning(
            "LLM is_configured()=False: keys are set for [%s] but none are "
            "permitted at runtime (LLM_ALLOW_FOREIGN_PROVIDERS=%s). "
            "AI filtering is DISABLED — running rule-based only.",
            ", ".join(configured_keys),
            allow_foreign,
        )
    return False
