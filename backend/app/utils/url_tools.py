import ipaddress
import socket
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

# Домены-агрегаторы, доски объявлений, справочники, социальные сети
AGGREGATOR_DOMAINS = {
    # Объявления и маркетплейсы
    "avito.ru", "avito.com", "youla.ru", "дром.рф", "drom.ru", "auto.ru", "autostat.ru",
    "farpost.ru", "irr.ru", "olx.ru", "baraholka.ru",
    # Карты и геосервисы
    "2gis.ru", "2gis.com", "maps.yandex.ru", "yandex.ru", "yandex.com", "maps.google.com",
    "google.com", "bing.com",
    # Справочники и каталоги
    "zoon.ru", "yell.ru", "flamp.ru", "otzovik.com", "irecommend.ru", "vseapteki.ru",
    "spravker.ru", "sprav.cc", "orgpage.ru", "gorabota.ru", "hh.ru", "superjob.ru",
    "rabota.ru", "career.ru", "zarplata.ru", "trudvsem.ru",
    "kompass.com", "rusprofile.ru", "sbis.ru", "spark-interfax.ru", "list-org.com",
    "checko.ru", "nalog.ru", "egrul.nalog.ru", "fedresurs.ru",
    "kartoteka.ru", "focus.kontur.ru", "zachestnyibiznes.ru",
    # B2B справочники и тендеры
    "tiu.ru", "blizko.ru", "prom.ua", "deal.by", "allbiz.ru",
    "pulscen.ru", "pulscen.com", "flagma.ru", "flagma.by",
    "tradedir.ru", "tradekey.com", "alibaba.com", "aliexpress.ru",
    "b2b.ru", "b2bbase.ru", "postavschiki.ru", "podimdelo.ru",
    # Строительные и отраслевые каталоги
    "stroyportal.ru", "supmle.com", "feech.com",
    "naydimaster.ru", "youdo.com", "profi.ru", "remontnik.ru",
    # Новости и медиа
    "rbc.ru", "companies.rbc.ru", "ria.ru", "tass.ru", "gazeta.ru", "kommersant.ru",
    "vedomosti.ru", "interfax.ru", "regnum.ru",
    # Социальные сети и мессенджеры
    "vk.com", "ok.ru", "facebook.com", "instagram.com", "twitter.com", "tiktok.com",
    "youtube.com", "rutube.ru", "t.me", "telegram.org",
    "whatsapp.com", "viber.com", "discord.com", "zoom.us",
    # Электронная коммерция
    "market.yandex.ru", "ozon.ru", "wildberries.ru", "lamoda.ru", "mvideo.ru",
    "eldorado.ru", "dns-shop.ru", "citylink.ru", "goods.ru",
    # Недвижимость и путешествия
    "cian.ru", "domclick.ru", "n1.ru", "realty.yandex.ru",
    "booking.com", "tripadvisor.com", "tripadvisor.ru",
    "spravka.ru", "altaspravka.ru", "infogeo.ru",
    "ukrtime.net", "cataloxy.ru", "unisender.com",
    # Энциклопедии и справочная информация
    "wikipedia.org", "wikimedia.org", "wiktionary.org", "wikiquote.org",
    "dic.academic.ru", "academic.ru", "slovari.ru", "cyclowiki.org",
    "bolshoyvopros.ru", "otvet.mail.ru", "answers.mail.ru",
    # Погода
    "gismeteo.ru", "gismeteo.com", "weather.com", "pogoda.ru", "pogoda.mail.ru",
    # Авто-форумы и развлекательные
    "drive2.ru", "drom.ru", "pikabu.ru", "fishki.net", "yaplakal.com",
    # Блог-платформы и контент-площадки
    "dzen.ru", "zen.yandex.ru", "habr.com", "vc.ru", "medium.com",
    "livejournal.com", "liveinternet.ru", "blogspot.com", "wordpress.com",
    "tjournal.ru", "the-village.ru",
    # Госсайты и образование
    "gov.ru", "mos.ru", "gosuslugi.ru", "edu.ru", "consultant.ru", "garant.ru",
    # Поисковики и стартовые страницы
    "mail.ru", "rambler.ru", "yahoo.com",
    # Файлохранилища и прочие нерелевантные
    "dropbox.com", "github.com", "gitlab.com", "bitbucket.org",
    "pinterest.com", "pinterest.ru", "flickr.com",
    # Дополнительные маркетплейсы и агрегаторы
    "satu.kz", "satu.ru", "olan.ru", "web-org.ru",
    "domamo.ru", "domofond.ru", "yandex.ua",
    # Туристические и не-бизнес
    "horosho-tam.ru", "tourister.ru", "tophotels.ru",
    # Юридические справочники и проверки контрагентов
    "sravni.ru", "e-ecolog.ru", "org77.ru", "rusprofile.ru",
    "list-org.com", "checko.ru", "sbis.ru", "spark-interfax.ru",
    "egrul.nalog.ru", "zachestnyibiznes.ru", "kartoteka.ru",
    "companium.ru", "find-org.com", "lexpr.ru", "elibrary.ru",
    "fedresurs.ru", "bankrot.fedresurs.ru", "arbitr.ru",
    "focus.kontur.ru", "kontragent.skrin.ru", "bo.nalog.ru",
    "rekvizitof.ru", "vbankcenter.ru", "companies.rbc.ru",
    # Вакансии и HR-платформы
    "hh.ru", "headhunter.ru", "superjob.ru", "rabota.ru",
    "zarplata.ru", "trudvsem.ru", "avito.ru", "youla.ru",
    "job.ru", "rabota.mail.ru", "jooble.org", "indeed.com",
    "glassdoor.com", "career.ru", "careerist.ru", "grc.ua",
    "work.ua", "jobs.ua", "tbru.ru", "vakant.ru",
    # Отзывы и рейтинги
    "irecommend.ru", "otzovik.com", "flamp.ru", "yell.ru",
    "zoon.ru", "spr.ru", "orgpage.ru", "otzyvru.com",
    "cataloxy.ru", "unisender.com", "otzyv.ru",
    # Карты и навигация (не сами компании)
    "yandex.ru", "maps.google.com", "google.com",
    # Прочие агрегаторы
    "2gis.ru", "gis.ru", "2gis.com",
    "prodoctorov.ru", "docdoc.ru", "napopravku.ru",
    "banki.ru", "sravni.com", "vsebanki.ru",
    "auto.ru", "drom.ru", "car.ru",
    "farpost.ru", "irr.ru", "olx.ru",
}

# UTM и трекинговые параметры для удаления
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name",
    "gclid", "fbclid", "yclid", "mc_cid", "mc_eid",
    "ref", "referral", "campaign_id", "ad_id",
    "_ga", "_gl", "msclkid", "dclid",
})


def extract_domain(raw_url: str) -> str:
    if not raw_url:
        return ""
    if not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"
    parsed = urlparse(raw_url.strip())
    host = parsed.netloc.lower().replace("www.", "").split(":")[0]
    if not host:
        return ""
    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        return ""
    return host


def is_real_domain(domain: str) -> bool:
    if not domain:
        return False
    if "." not in domain:
        return False
    blocked = ("localhost", ".local", ".internal", "example.", "test.", ".invalid", ".test")
    return not any(tag in domain for tag in blocked)


def is_aggregator_domain(domain: str) -> bool:
    domain = domain.lower().strip()
    if not domain:
        return False
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in AGGREGATOR_DOMAINS)


def is_junk_result(title: str, snippet: str = "") -> bool:
    """Check if a search result is junk (vacancy, liquidated company, etc)."""
    text = f"{title} {snippet}".lower().replace("ё", "е")
    junk_patterns = [
        # Vacancies
        "вакансия", "вакансии", "работа в компании", "ищем сотрудник",
        "зарплата от", "требуется", "резюме", "соискател",
        "оператор чпу", "менеджер по продаж", "устроиться на работ",
        # Liquidated / closed
        "ликвидирован", "ликвидация", "прекратило деятельность",
        "исключен из егрюл", "исключено из егрюл", "недействующ",
        "банкрот", "конкурсное производств",
        # Legal / registry pages
        "инн ", "огрн ", "кпп ", "окпо ", "юридический адрес",
        "реквизиты компании", "выписка из егрюл", "карточка предприятия",
        "проверка контрагент", "сведения о юридическом",
        "судебные дела", "арбитражные дела", "исполнительное производств",
        # Review / rating aggregator pages
        "отзывы о компании", "отзывы сотрудников", "рейтинг компании",
        "все отзывы", "оставить отзыв",
    ]
    return any(p in text for p in junk_patterns)


def get_base_domain(domain: str) -> str:
    domain = domain.lower().strip()
    if not domain:
        return ""
    parts = [part for part in domain.split(".") if part]
    if len(parts) < 2:
        return domain
    second_level_suffixes = {"co.uk", "com.au", "com.br", "co.jp", "co.kr", "com.tr", "com.cn", "co.nz"}
    candidate_suffix = ".".join(parts[-2:])
    if len(parts) >= 3 and candidate_suffix in second_level_suffixes:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_url(raw_url: str) -> str:
    raw_url = raw_url.strip()
    if not raw_url:
        return ""
    if not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"
    parsed = urlparse(raw_url)
    host = extract_domain(raw_url)
    if not is_real_domain(host):
        return ""
    path = parsed.path.rstrip("/")
    # Нормализуем типовые index-страницы
    if path in ("/index.html", "/index.htm", "/index.php", "/index.asp", "/default.html"):
        path = ""
    # Удаляем UTM/трекинговые параметры, сохраняем значимые
    clean_params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    clean_query = urlencode(clean_params) if clean_params else ""
    return urlunparse((parsed.scheme or "https", host, path, "", clean_query, ""))


_UNSAFE_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


def _is_safe_url(url: str) -> bool:
    """Validate that a URL does not point to internal/private network addresses (SSRF protection)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Only allow http and https schemes
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        return False

    # Reject known internal hostnames
    if hostname in _UNSAFE_HOSTNAMES:
        return False
    # Reject .local, .internal, .localhost TLDs
    if hostname.endswith((".local", ".internal", ".localhost")):
        return False

    # Resolve hostname and check IP ranges
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Cannot resolve -- allow the request; httpx will fail naturally
        return True

    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False

    return True
