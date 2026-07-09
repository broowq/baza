"""Yandex Search API v2 — замена мёртвого SearXNG-скрейпинга.

SearXNG на проде вернул чистый мусор (ozon/avito/wikipedia) — глобальные
движки на RU-запросы отдают маркетплейсы, их выбрасывает фильтр агрегаторов,
на выходе ≈0 сайтов компаний. Yandex Search API v2 (Yandex Cloud) — RU-выдача
без капчи. Тесты: парсинг XML классической схемы Яндекса, гейтинг по конфигу,
фолбэк на SearXNG при отсутствии ключа / ошибке API.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import app.services.lead_collection as lc


# Реалистичный XML Яндекса: yandexsearch>response>results>grouping>group>doc.
_YANDEX_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <results>
      <grouping>
        <group>
          <doc>
            <url>https://sibпилорама.ru/kontakty</url>
            <domain>sibпилорама.ru</domain>
            <title>Сиб<hlword>пилорама</hlword> — производство пиломатериалов | Томск</title>
            <headline>Пиломатериалы оптом</headline>
            <passages>
              <passage>Продаём <hlword>пиломатериал</hlword>, вагонку, брус. Тел. +7 3822 00-00-00</passage>
            </passages>
          </doc>
        </group>
        <group>
          <doc>
            <url>https://www.ozon.ru/category/pilorama/</url>
            <domain>www.ozon.ru</domain>
            <title>Пилорама купить на OZON</title>
            <passages><passage>маркетплейс</passage></passages>
          </doc>
        </group>
        <group>
          <doc>
            <url>https://lespromtomsk.ru/</url>
            <domain>lespromtomsk.ru</domain>
            <title>ЛесПром Томск</title>
          </doc>
        </group>
      </grouping>
    </results>
  </response>
</yandexsearch>"""


def test_parse_yandex_xml_extracts_companies_and_drops_aggregators():
    items = lc._parse_yandex_search_xml(_YANDEX_XML)
    domains = [it["domain"] for it in items]
    # ozon.ru — агрегатор, выброшен; реальные сайты компаний — остались
    assert "www.ozon.ru" not in domains
    assert any("sib" in d for d in domains)
    assert "lespromtomsk.ru" in domains
    first = next(it for it in items if "sib" in it["domain"])
    # <hlword>-подсветка вычищена из title и passage
    assert "<hlword>" not in first["company"] and "hlword" not in first["company"]
    assert first["company"].startswith("Сибпилорама")  # обрезано по разделителю «|»
    assert "+7 3822" in first["snippet"]
    assert first["source"] == "yandex_search"
    # doc без passages/headline не падает (lespromtomsk)
    lp = next(it for it in items if it["domain"] == "lespromtomsk.ru")
    assert lp["snippet"] == ""


def test_parse_yandex_xml_malformed_returns_empty():
    assert lc._parse_yandex_search_xml("не xml вовсе") == []
    assert lc._parse_yandex_search_xml("") == []


_YANDEX_ERROR_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <error code="55">Ключ доступа к API некорректен</error>
  </response>
</yandexsearch>"""


def test_parse_yandex_xml_error_response_raises():
    """HTTP 200 + <error> внутри XML (мисконфиг) поднимает _YandexSearchError,
    чтобы диспетчер откатился на SearXNG, а не тихо получил 0 сайтов."""
    import pytest
    with pytest.raises(lc._YandexSearchError):
        lc._parse_yandex_search_xml(_YANDEX_ERROR_XML)


def test_yandex_search_configured_gating():
    assert lc._yandex_search_configured(SimpleNamespace(yandex_search_api_key="k", yandex_search_folder_id="f"))
    assert not lc._yandex_search_configured(SimpleNamespace(yandex_search_api_key="k", yandex_search_folder_id=""))
    assert not lc._yandex_search_configured(SimpleNamespace(yandex_search_api_key="", yandex_search_folder_id="f"))


def test_yandex_search_fetch_page_builds_request_and_decodes(monkeypatch):
    """Клиент шлёт корректный POST (Api-Key, folderId, 0-индекс page) и
    декодирует base64-XML в кандидатов."""
    captured = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"rawData": base64.b64encode(_YANDEX_XML.encode("utf-8")).decode("ascii")}

    class _Client:
        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return _Resp()

    settings = SimpleNamespace(
        yandex_search_api_key="test-key", yandex_search_folder_id="test-folder",
        yandex_search_region="", yandex_search_timeout_seconds=15.0,
    )
    items = lc._yandex_search_fetch_page(_Client(), "пилорама Томск", page=1, settings=settings)
    assert captured["url"] == lc._YANDEX_SEARCH_URL
    assert captured["headers"]["Authorization"] == "Api-Key test-key"
    assert captured["body"]["folderId"] == "test-folder"
    assert captured["body"]["query"]["queryText"] == "пилорама Томск"
    assert captured["body"]["query"]["page"] == 0  # наш page=1 → яндекс 0-индекс
    assert captured["body"]["responseFormat"] == "FORMAT_XML"
    # регион не добавлен, когда пуст
    assert "region" not in captured["body"]
    assert any("sib" in it["domain"] for it in items)


def test_yandex_search_region_added_when_set(monkeypatch):
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"rawData": ""}
    class _Client:
        def post(self, url, json=None, headers=None, timeout=None):
            _Client.body = json
            return _Resp()
    settings = SimpleNamespace(
        yandex_search_api_key="k", yandex_search_folder_id="f",
        yandex_search_region="213", yandex_search_timeout_seconds=15.0,
    )
    lc._yandex_search_fetch_page(_Client(), "q", page=1, settings=settings)
    assert _Client.body["region"] == "213"
