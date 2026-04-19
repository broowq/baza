import re
import json
import phonenumbers

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# mailto: hrefs are the highest-confidence email source on websites
MAILTO_REGEX = re.compile(r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})', re.IGNORECASE)
# VK community / Telegram channel URLs — useful for B2B firms without a website
VK_REGEX = re.compile(r'https?://(?:vk\.com|m\.vk\.com)/([a-zA-Z0-9_.\-]{3,})', re.IGNORECASE)
TG_REGEX = re.compile(r'https?://(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{3,})', re.IGNORECASE)
PHONE_REGEX = re.compile(
    r"(?:(?:\+7|8)[\s\-\(]?(?:\d{3}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2})"
    r"|(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3}[\s\-]?\d{2,4}[\s\-]?\d{2,4})"
)
JSON_LD_REGEX = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
EVENT_ATTR_RE = re.compile(r"\son\w+\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)

# Ключевые слова для поиска адресов (русские и английские)
ADDRESS_HINTS_RU = (
    "ул.", "улица", "пр-т", "проспект", "пл.", "площадь", "пер.", "переулок",
    "д.", "дом", "офис", "кв.", "этаж", "бизнес-центр", "бц",
    "г.", "город", "область", "край", "район",
    "индекс", "почтовый", "юридический адрес", "фактический адрес",
)
ADDRESS_HINTS_EN = ("street", "st.", "avenue", "road", "suite", "office", "zip", "city")
ALL_ADDRESS_HINTS = ADDRESS_HINTS_RU + ADDRESS_HINTS_EN

# Паттерны для отсева мусора (JavaScript, CSS, HTML артефакты)
CODE_PATTERNS = re.compile(
    r"(?:function\s*[\(\{]|=>|var\s+\w+|let\s+\w+|const\s+\w+|\.setJ[Ss]|BX\.|bitrix|jQuery"
    r"|window\.|document\.|console\.|\.push\(|\.map\(|\.filter\(|\.forEach\("
    r"|\bif\s*\(|\belse\s*\{|\bwhile\s*\(|\bfor\s*\("
    r"|box-sizing|border-box|margin:|padding:|display:|position:|overflow:|z-index"
    r"|font-size|font-family|background|opacity:|transition:|animation:|transform:"
    r"|rgba?\(|webkit-|moz-|-ms-|@media|@keyframes|!important"
    r"|\{[^}]{0,30}:[^}]{0,30}\}|<[a-zA-Z][^>]{0,100}>|&\w{2,6};|\\u[0-9a-fA-F]{4}"
    r"|getElementById|querySelector|className|innerHTML|addEventListener|hasOwnProperty"
    r"|\bsetTimeout\b|\bsetInterval\b|\.src\s*=|\.href\s*=|\beval\s*\()"
)
# Минимальные и максимальные длины строки для адреса
ADDRESS_MIN_LEN = 10
ADDRESS_MAX_LEN = 250


def _normalize_phone(value: str) -> str:
    cleaned = re.sub(r"[^\d+\- \(\)]", "", value.strip())
    try:
        # Пробуем парсить как российский номер
        parsed = phonenumbers.parse(cleaned, "RU")
        if not phonenumbers.is_valid_number(parsed):
            return ""
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        # Отсеиваем мусорные номера
        if e164 in {"+70000000000", "+79999999999", "+71111111111"}:
            return ""
        return e164
    except Exception:
        pass
    # Запасной вариант — международный парсинг
    try:
        if value.strip().startswith("+"):
            parsed = phonenumbers.parse(value.strip(), None)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return ""


def _is_valid_address_line(line: str) -> bool:
    """Проверяет, что строка — реальный адрес, а не код/мусор."""
    stripped = line.strip()
    if not (ADDRESS_MIN_LEN <= len(stripped) <= ADDRESS_MAX_LEN):
        return False
    if CODE_PATTERNS.search(stripped):
        return False
    # CSS-класс типа location_city, _location_, data-* и т.п.
    if re.match(r'^[a-z_][a-z0-9_-]*$', stripped, re.IGNORECASE):
        return False
    # JSON-фрагмент (только ASCII-ключи — кириллические слова типа "Адрес:" не считаем JSON)
    if re.match(r'^["\']?[a-zA-Z_][a-zA-Z0-9_]*["\']?\s*:', stripped):
        return False
    # Начало JS-комментария
    if stripped.startswith("//") or stripped.startswith("/*"):
        return False
    # Должны быть в основном буквы и цифры
    letter_digit_ratio = sum(1 for c in stripped if c.isalnum()) / max(len(stripped), 1)
    if letter_digit_ratio < 0.35:
        return False
    # Адрес должен содержать либо цифру (номер дома), либо явный маркер адреса
    has_number = bool(re.search(r'\d', stripped))
    has_addr_hint = any(hint in stripped.lower() for hint in ADDRESS_HINTS_RU)
    if not has_number and not has_addr_hint:
        return False
    return True


def _walk_json(value: object, emails: set[str], phones: set[str], addresses: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"email", "emails"} and isinstance(item, str):
                m = EMAIL_REGEX.fullmatch(item.strip())
                if m:
                    emails.add(item.strip().lower())
            if lowered in {"telephone", "phone", "tel"} and isinstance(item, str):
                normalized = _normalize_phone(item)
                if normalized:
                    phones.add(normalized)
            if lowered in {"address", "streetaddress", "postaladdress"}:
                if isinstance(item, str):
                    candidate = item.strip()
                    if _is_valid_address_line(candidate):
                        addresses.append(candidate)
                elif isinstance(item, dict):
                    parts = []
                    for field in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"):
                        v = item.get(field, "")
                        if isinstance(v, str) and v.strip():
                            parts.append(v.strip())
                    if not parts:
                        parts = [str(v).strip() for v in item.values() if str(v).strip()]
                    merged = ", ".join(parts)
                    if _is_valid_address_line(merged):
                        addresses.append(merged)
            _walk_json(item, emails, phones, addresses)
    elif isinstance(value, list):
        for item in value:
            _walk_json(item, emails, phones, addresses)


def extract_contacts(text: str, html: str | None = None) -> dict:
    raw_html = html or ""
    # Глубокая очистка HTML перед парсингом
    sanitized = SCRIPT_STYLE_RE.sub(" ", raw_html)
    sanitized = EVENT_ATTR_RE.sub("", sanitized)
    # Удаляем все HTML-теги
    sanitized_text = re.sub(r"<[^>]+>", " ", sanitized)
    # Декодируем HTML-entities
    sanitized_text = re.sub(r"&[a-zA-Z]{2,6};", " ", sanitized_text)
    # Убираем лишние пробелы
    sanitized_text = re.sub(r"\s+", " ", sanitized_text)

    combined = f"{text}\n{sanitized_text}"

    # Email — extract from BOTH mailto: hrefs (high signal) and inline text.
    # mailto: emails are the highest-confidence source — sites put them there
    # specifically for users to click. Promote them to top of list.
    mailto_emails: list[str] = []
    for m in MAILTO_REGEX.finditer(raw_html):
        e = m.group(1).strip().lower()
        if e and e not in mailto_emails:
            mailto_emails.append(e)

    text_emails = sorted({m.group(0).lower() for m in EMAIL_REGEX.finditer(combined)})

    # Merge: mailto first (priority), then text-extracted
    all_emails = mailto_emails + [e for e in text_emails if e not in mailto_emails]

    # Filter junk: technical placeholders, tracking domains, image extensions
    blocked = {"example@example.com", "test@test.com", "noreply@noreply.com"}
    emails = [
        e for e in all_emails
        if e not in blocked
        and not any(pat in e for pat in (
            "example.", "test.", "localhost", "placeholder", "yoursite.", "domain.",
            "sentry.io", "@sentry", "@noreply", "no-reply",
            ".png@", ".jpg@", ".gif@", ".svg@", ".webp@",  # filename-as-email
        ))
        and len(e) <= 254  # RFC 5321 max
    ]
    # Boost B2B contact-style emails to top (info@, sales@, office@, etc.)
    contact_prefixes = ("info@", "sales@", "contact@", "office@", "hello@", "client@",
                        "manager@", "zakaz@", "order@", "shop@", "kontakt@", "support@")
    emails.sort(key=lambda e: (0 if e.startswith(contact_prefixes) else 1, e))

    # Телефоны
    phones: list[str] = []
    seen_phones: set[str] = set()
    for m in PHONE_REGEX.finditer(combined):
        normalized = _normalize_phone(m.group(0))
        if normalized and normalized not in seen_phones:
            seen_phones.add(normalized)
            phones.append(normalized)

    # Адреса из текста
    addresses: list[str] = []
    seen_addr: set[str] = set()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        lower = line.lower()
        if any(hint in lower for hint in ALL_ADDRESS_HINTS) and _is_valid_address_line(line):
            key = re.sub(r"\s+", " ", line.lower().strip())
            if key not in seen_addr:
                seen_addr.add(key)
                addresses.append(line)

    # Структурированные данные из JSON-LD
    if raw_html:
        for match in JSON_LD_REGEX.finditer(raw_html):
            payload = match.group("body").strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except Exception:
                continue
            ld_emails: set[str] = set()
            ld_phones: set[str] = set()
            ld_addresses: list[str] = []
            _walk_json(parsed, ld_emails, ld_phones, ld_addresses)
            for e in ld_emails:
                if e not in set(emails):
                    emails.append(e)
            for p in ld_phones:
                if p not in seen_phones:
                    seen_phones.add(p)
                    phones.append(p)
            for a in ld_addresses:
                key = re.sub(r"\s+", " ", a.lower().strip())
                if key not in seen_addr:
                    seen_addr.add(key)
                    addresses.append(a)

    # Social channels — extract VK / Telegram links (useful for B2B firms
    # that don't have a website but have an active community).
    vk_links: list[str] = []
    for m in VK_REGEX.finditer(raw_html):
        slug = m.group(1).rstrip(".,/")
        # Skip generic VK pages (vk.com/feed, /im, /club0)
        if slug.lower() in ("feed", "im", "settings", "club0", "club", "search", "wall"):
            continue
        url = f"https://vk.com/{slug}"
        if url not in vk_links:
            vk_links.append(url)

    tg_links: list[str] = []
    for m in TG_REGEX.finditer(raw_html):
        slug = m.group(1).rstrip(".,/")
        if slug.lower() in ("share", "joinchat", "addstickers", "iv"):
            continue
        url = f"https://t.me/{slug}"
        if url not in tg_links:
            tg_links.append(url)

    return {
        # Don't re-sort emails — preserve mailto-first + contact-prefix priority.
        "emails": emails[:5],
        "phones": sorted(phones)[:5],
        "addresses": addresses[:3],
        "social": {
            "vk": vk_links[:3],
            "telegram": tg_links[:3],
        },
    }
