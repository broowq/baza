from app.utils.contact_parser import extract_contacts
from app.utils.url_tools import get_base_domain, is_aggregator_domain, normalize_url


def test_normalize_url():
    assert normalize_url("acme.com/path/") == "https://acme.com/path"
    assert normalize_url("https://WWW.Acme.com") == "https://acme.com"
    assert normalize_url("https://пример.рф/path?utm_source=x&gclid=123") == "https://xn--e1afmkfd.xn--p1ai/path"


def test_extract_contacts():
    # example.com специально фильтруется; используем реальный домен
    text = "Contact us at team@firma.ru or +7 916 123-45-67\nул. Ленина, д. 10, офис 5"
    contacts = extract_contacts(text)
    assert "team@firma.ru" in contacts["emails"]
    assert contacts["phones"]
    assert contacts["addresses"]


def test_aggregator_domain():
    assert is_aggregator_domain("www.2gis.ru")
    assert not is_aggregator_domain("company-example.ru")


def test_schema_org_contacts_extraction():
    html = """
    <script type="application/ld+json">
      {"@type":"Organization","email":"sales@example.com","telephone":"+7 (916) 123-45-67","address":"ул. Пушкина, д.1"}
    </script>
    """
    contacts = extract_contacts("", html=html)
    assert "sales@example.com" in contacts["emails"]
    assert contacts["phones"]
    assert contacts["addresses"]


def test_get_base_domain():
    assert get_base_domain("sales.company.ru") == "company.ru"
    assert get_base_domain("shop.example.co.uk") == "example.co.uk"
