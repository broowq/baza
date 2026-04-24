"""Tests for the website contact-enrichment pipeline.

Covers the critical bugs that were leaving leads "не обогащён" in prod:
- follow_redirects=False swallowed every redirect-backed site
- /footer /header paths wasted budget and added no signal
- timeout=6s was too tight for RU shared hosting

Fixtures use respx to mock httpx so no real network I/O.
"""
from __future__ import annotations

import respx
import httpx
import pytest

from app.services.lead_collection import enrich_website_contacts


# --- HTML fixtures ------------------------------------------------------------

_FOOTER_WITH_CONTACTS = """
<!doctype html><html><head><title>Птицефабрика Юг</title></head><body>
<main>...</main>
<footer>
  <p>Наш адрес: г. Томск, ул. Фермерская, д. 12, офис 4</p>
  <p>Телефон: <a href="tel:+73822201136">+7 (3822) 20-11-36</a></p>
  <p>Почта: <a href="mailto:info@ptitsa-yug.ru">info@ptitsa-yug.ru</a></p>
</footer>
</body></html>
"""

_CONTACTS_PAGE = """
<!doctype html><html><body>
<h1>Контакты</h1>
<ul>
  <li>Email: <a href="mailto:sales@mpf-russia.com">sales@mpf-russia.com</a></li>
  <li>Тел: +7 383 220 55 33</li>
  <li>Адрес: 630049, г. Новосибирск, ул. Красноярская, 35</li>
</ul>
</body></html>
"""

_EMPTY_HOME = "<!doctype html><html><body><h1>Главная</h1></body></html>"

_JSON_LD_PAGE = """
<!doctype html><html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Агрохолдинг СТЕПЬ",
  "email": "office@ahstep.ru",
  "telephone": "+78123333333",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "ул. Промышленная, 1",
    "addressLocality": "Санкт-Петербург",
    "postalCode": "196105"
  }
}
</script>
</head><body>Home</body></html>
"""


# --- helpers ------------------------------------------------------------------

def _mock_all_paths(mock: respx.MockRouter, host: str, body: str, status: int = 200) -> None:
    """Make every candidate path return the same body."""
    # Match both root and any path on the host — respx's `host=` filter
    # matches exact host, with regex for path.
    mock.get(url__regex=rf"https?://{host}(/.*)?").mock(
        return_value=httpx.Response(status, text=body, headers={"content-type": "text/html"})
    )


# --- tests --------------------------------------------------------------------

@respx.mock
def test_follow_redirects_now_works(respx_mock: respx.MockRouter) -> None:
    """The #1 critical bug fix: when a site issues 301→https or www-redirect,
    we MUST follow it, not drop the response."""
    # Simulate http → https redirect
    respx_mock.get("http://ptitsa-yug.ru/").mock(
        return_value=httpx.Response(301, headers={"location": "https://ptitsa-yug.ru/"})
    )
    respx_mock.get("https://ptitsa-yug.ru/").mock(
        return_value=httpx.Response(200, text=_FOOTER_WITH_CONTACTS,
                                    headers={"content-type": "text/html"})
    )
    # Other paths 404 so we only exercise the redirect
    respx_mock.get(url__regex=r"https?://ptitsa-yug.ru/.+").mock(
        return_value=httpx.Response(404)
    )

    result = enrich_website_contacts("http://ptitsa-yug.ru")

    assert "info@ptitsa-yug.ru" in result["emails"], (
        f"redirect-followed page should yield email, got {result}"
    )
    assert any("+7" in p or p.startswith("+7") for p in result["phones"]), result
    assert result["addresses"], result


@respx.mock
def test_contacts_page_is_found(respx_mock: respx.MockRouter) -> None:
    """/contacts path gets tried and yields structured data."""
    respx_mock.get("https://mpf-russia.com/").mock(
        return_value=httpx.Response(200, text=_EMPTY_HOME, headers={"content-type": "text/html"})
    )
    respx_mock.get("https://mpf-russia.com/contacts").mock(
        return_value=httpx.Response(200, text=_CONTACTS_PAGE, headers={"content-type": "text/html"})
    )
    # Anything else 404
    respx_mock.get(url__regex=r"https?://mpf-russia.com/.+").mock(
        return_value=httpx.Response(404)
    )

    result = enrich_website_contacts("https://mpf-russia.com")

    assert "sales@mpf-russia.com" in result["emails"], result
    assert result["phones"], result


@respx.mock
def test_json_ld_structured_data_extracted(respx_mock: respx.MockRouter) -> None:
    """Organization JSON-LD should yield email + phone + address even if
    the visible HTML has nothing."""
    respx_mock.get("https://ahstep.ru/").mock(
        return_value=httpx.Response(200, text=_JSON_LD_PAGE, headers={"content-type": "text/html"})
    )
    respx_mock.get(url__regex=r"https?://ahstep.ru/.+").mock(
        return_value=httpx.Response(404)
    )

    result = enrich_website_contacts("https://ahstep.ru")

    assert "office@ahstep.ru" in result["emails"], result
    assert any(p.startswith("+7") for p in result["phones"]), result


@respx.mock
def test_aggregator_domains_skipped(respx_mock: respx.MockRouter) -> None:
    """Known aggregator domains must not be scraped at all."""
    # No mocks installed — if enrichment tried to fetch, respx would raise.
    result = enrich_website_contacts("https://2gis.ru/moscow/branches/111")
    assert result == {"emails": [], "phones": [], "addresses": []}


@respx.mock
def test_empty_result_when_no_contacts_anywhere(respx_mock: respx.MockRouter) -> None:
    """A site that serves an empty-looking page everywhere should return
    empty lists, not crash."""
    respx_mock.get(url__regex=r"https?://boring-farm.ru(/.*)?").mock(
        return_value=httpx.Response(200, text=_EMPTY_HOME, headers={"content-type": "text/html"})
    )

    result = enrich_website_contacts("https://boring-farm.ru")

    assert result["emails"] == []
    assert result["phones"] == []
    # addresses may contain the empty-home marker stripped — just ensure no crash


@respx.mock
def test_timeout_is_tolerated(respx_mock: respx.MockRouter) -> None:
    """If a single path times out, we continue to the next one, not bail."""
    respx_mock.get("https://slow-farm.ru/").mock(side_effect=httpx.TimeoutException("test"))
    respx_mock.get("https://slow-farm.ru/contacts").mock(
        return_value=httpx.Response(200, text=_CONTACTS_PAGE, headers={"content-type": "text/html"})
    )
    respx_mock.get(url__regex=r"https?://slow-farm.ru/.+").mock(
        return_value=httpx.Response(404)
    )

    result = enrich_website_contacts("https://slow-farm.ru")

    assert "sales@mpf-russia.com" in result["emails"], (
        "after the root timed out, /contacts should still be fetched"
    )


@respx.mock
def test_footer_header_paths_not_requested(respx_mock: respx.MockRouter) -> None:
    """/footer and /header were removed from candidate_paths — they are
    CSS/JS fragments, not real URLs. This test pins the change."""
    root = respx_mock.get("https://pinned-domain.ru/").mock(
        return_value=httpx.Response(200, text=_EMPTY_HOME, headers={"content-type": "text/html"})
    )
    footer = respx_mock.get("https://pinned-domain.ru/footer").mock(
        return_value=httpx.Response(200, text=_EMPTY_HOME)
    )
    header = respx_mock.get("https://pinned-domain.ru/header").mock(
        return_value=httpx.Response(200, text=_EMPTY_HOME)
    )
    # Allow any other path
    respx_mock.get(url__regex=r"https?://pinned-domain.ru/.+").mock(
        return_value=httpx.Response(404)
    )

    enrich_website_contacts("https://pinned-domain.ru")

    assert root.called, "root / must still be fetched"
    assert not footer.called, "/footer must no longer be in candidate_paths"
    assert not header.called, "/header must no longer be in candidate_paths"
