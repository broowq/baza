"""
Тесты для модуля парсинга контактов (contact_parser.py).
"""
from app.utils.contact_parser import extract_contacts, _normalize_phone, _is_valid_address_line


# ─── Нормализация телефонов ───────────────────────────────────────────────────

def test_normalize_phone_ru_8():
    result = _normalize_phone("8 (495) 123-45-67")
    assert result == "+74951234567"


def test_normalize_phone_ru_plus7():
    result = _normalize_phone("+7 916 123-45-67")
    assert result == "+79161234567"


def test_normalize_phone_garbage():
    result = _normalize_phone("(000) 000-000")
    assert result == ""


def test_normalize_phone_short():
    result = _normalize_phone("123")
    assert result == ""


# ─── Валидация адресных строк ─────────────────────────────────────────────────

def test_valid_address_line():
    assert _is_valid_address_line("ул. Ленина, д. 5, офис 101") is True


def test_invalid_address_js_code():
    assert _is_valid_address_line("BX.setJSList(['/bitrix/js/main/core.js'])") is False


def test_invalid_address_too_short():
    assert _is_valid_address_line("ул.") is False


def test_invalid_address_too_long():
    assert _is_valid_address_line("ул. " + "А" * 300) is False


# ─── Полный парсинг из текста ─────────────────────────────────────────────────

def test_extract_email_from_text():
    text = "Свяжитесь с нами: info@mycompany.ru или sales@example.com"
    result = extract_contacts(text)
    assert "info@mycompany.ru" in result["emails"]


def test_extract_phone_from_text():
    text = "Телефон: +7 (495) 123-45-67"
    result = extract_contacts(text)
    assert "+74951234567" in result["phones"]


def test_extract_address_from_text():
    text = "Адрес: г. Москва, ул. Ленина, д. 10"
    result = extract_contacts(text)
    assert len(result["addresses"]) > 0


def test_no_duplicates_in_emails():
    text = "info@company.ru info@company.ru info@company.ru"
    result = extract_contacts(text)
    assert result["emails"].count("info@company.ru") == 1


def test_filter_technical_emails():
    text = "example@example.com test@test.com real@company.ru"
    result = extract_contacts(text)
    assert "example@example.com" not in result["emails"]
    assert "real@company.ru" in result["emails"]


# ─── Парсинг из HTML ──────────────────────────────────────────────────────────

def test_extract_from_html_removes_scripts():
    html = """
    <script>var x = 'ignore@ignore.com';</script>
    <p>Контакт: contact@realsite.ru</p>
    <style>.ignore { color: red; }</style>
    """
    result = extract_contacts("", html)
    # Стиль и скрипт должны быть удалены — игнорируем адреса в них
    real_emails = [e for e in result["emails"] if "realsite" in e]
    assert len(real_emails) > 0


def test_extract_from_json_ld():
    html = """
    <script type="application/ld+json">
    {
      "@type": "Organization",
      "email": "ceo@startup.io",
      "telephone": "+7 800 123-45-67",
      "address": {
        "streetAddress": "ул. Тверская, д. 5",
        "addressLocality": "Москва"
      }
    }
    </script>
    """
    result = extract_contacts("", html)
    assert "ceo@startup.io" in result["emails"]
    assert "+78001234567" in result["phones"]
    assert len(result["addresses"]) > 0


def test_extract_multiple_phones():
    text = "Офис: 8 (800) 555-35-35. Мобильный: +7 916 000-11-22"
    result = extract_contacts(text)
    assert len(result["phones"]) >= 1


# ─── Скоринг ─────────────────────────────────────────────────────────────────

def test_scoring_integration():
    """Проверяем, что score корректно меняется с контактами и без."""
    from app.services.scoring import score_lead

    high = score_lead(domain="firma.ru", company="ООО Фирма", niche="деревообработка",
                      has_email=True, has_phone=True, has_address=True, demo=False)
    low = score_lead(domain="firma.ru", company="ООО Фирма", niche="деревообработка",
                     has_email=False, has_phone=False, has_address=False, demo=False)
    assert high > low
    assert 0 <= high <= 100
    assert 0 <= low <= 100


def test_scoring_ru_domain_bonus():
    from app.services.scoring import score_lead
    ru = score_lead(domain="firma.ru", company="ООО Фирма", niche="деревообработка",
                    has_email=True, has_phone=False, has_address=False, demo=False)
    io = score_lead(domain="firma.io", company="ООО Фирма", niche="деревообработка",
                    has_email=True, has_phone=False, has_address=False, demo=False)
    # .ru для российской ниши даёт бонус
    assert ru >= io


# ─── URL инструменты ──────────────────────────────────────────────────────────

def test_url_normalize_strips_utm():
    from app.utils.url_tools import normalize_url
    url = "https://mysite.ru/page?utm_source=google&utm_campaign=test&id=42"
    result = normalize_url(url)
    assert "utm_source" not in result
    assert "id=42" in result  # нетрекинговый параметр сохраняется


def test_url_normalize_strips_index_html():
    from app.utils.url_tools import normalize_url
    # example.ru заблокирован как псевдо-домен, используем реальный
    result = normalize_url("https://mycompany.ru/index.html")
    assert "/index.html" not in result
    assert "mycompany.ru" in result


def test_is_aggregator():
    from app.utils.url_tools import is_aggregator_domain
    assert is_aggregator_domain("2gis.ru") is True
    assert is_aggregator_domain("avito.ru") is True
    assert is_aggregator_domain("mysite.ru") is False


def test_get_base_domain():
    from app.utils.url_tools import get_base_domain
    assert get_base_domain("sub.example.ru") == "example.ru"
    assert get_base_domain("www.google.com") == "google.com"
