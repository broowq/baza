"""Анти-мультиакк защита регистрации (14.07.2026).

Появилась вместе с включением подтверждения почты: триал (10 разовых лидов
на Free) без неё фермится скриптом — регистрация на выдуманную почту стоила
ноль. Верификация закрывает выдуманные адреса, этот модуль закрывает обходы
самой верификации. Три слоя:

1. Нормализация identity почты — «vasya+2@gmail.com», «v.a.s.y.a@gmail.com»
   и «vasya@googlemail.com» суть один ящик; храним каноническую форму в
   users.email_normalized и 409-им повтор. Иначе один Gmail = бесконечные
   триалы: plus-тег и точки Gmail игнорирует, письмо с подтверждением
   доходит в тот же inbox.
2. Блок-лист одноразовых почт — temp-mail и им подобные дают рабочий inbox
   за секунды, верификация их не останавливает.
3. Суточный лимит регистраций с IP — HTTP-tier в main.py (10/мин) душит
   только burst; фермерству хватает 1/мин. Считаем ПОПЫТКИ атомарным INCR
   (без гонки check-then-act), поэтому потолок 5 — с запасом на опечатки
   легитимного пользователя (409 по email/имени орги тоже тратит попытку).

Чего тут осознанно НЕТ: капчи (внешняя зависимость + трение на лендинге;
добавим, если слои начнут пробивать) и привязки триала к IP (офисные NAT
дают ложные срабатывания на честных командах).
"""
from __future__ import annotations

import hashlib
import logging
import time

import redis
from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

# Домены-провайдеры одноразовых ящиков. Матчинг: сам домен и любой его
# поддомен (у многих провайдеров ротация вида abc123.mailinator.com).
# Список курируемый, не исчерпывающий — расширяется без деплоя через
# DISPOSABLE_EMAIL_DOMAINS_EXTRA (запятая-разделитель) в .env.
_DISPOSABLE_DOMAINS = frozenset({
    "temp-mail.org", "temp-mail.ru", "temp-mail.io", "tempmail.com",
    "tempmailo.com", "tempmail.plus", "tmpmail.org", "tmpmail.net",
    "tempr.email", "discard.email", "mailinator.com", "yopmail.com",
    "yopmail.fr", "guerrillamail.com", "guerrillamail.net",
    "guerrillamail.org", "guerrillamail.biz", "sharklasers.com", "grr.la",
    "10minutemail.com", "10minemail.com", "minuteinbox.com", "dropmail.me",
    "getnada.com", "nada.email", "mohmal.com", "maildrop.cc",
    "dispostable.com", "mintemail.com", "mytemp.email", "tempinbox.com",
    "throwawaymail.com", "emailondeck.com", "moakt.com", "moakt.cc",
    "inboxkitten.com", "mail.tm", "mail.gw", "1secmail.com", "1secmail.org",
    "1secmail.net", "mailforspam.com", "crazymailing.com", "mailsac.com",
    "fakeinbox.com", "trashmail.com", "trash-mail.com", "mailcatch.com",
    "mailnesia.com", "etempmail.net", "disbox.net", "spambog.com",
    "spambog.ru", "burnermail.io", "mailtemp.uk",
    # NB: internxt.com здесь НЕ место — это легитимная компания (их
    # temp-mail-сервис выдаёт адреса на ДРУГИХ доменах), ревью 14.07.
})

# Домены с алиасами/эквивалентностью логинов. Приводим к каноническому,
# чтобы vasya@ya.ru == vasya@yandex.ru (один ящик, разные вывески).
# NB: bk.ru/list.ru/inbox.ru — НЕ алиасы mail.ru (отдельные ящики одной
# группы), их сюда нельзя; они учтены во FREEMAIL_DOMAINS ниже.
_DOMAIN_ALIASES = {
    "googlemail.com": "gmail.com",
    "ya.ru": "yandex.ru",
    "yandex.com": "yandex.ru",
    "yandex.by": "yandex.ru",
    "yandex.kz": "yandex.ru",
    "yandex.ua": "yandex.ru",
    "yandex.com.tr": "yandex.ru",
    "yandex.fr": "yandex.ru",
    "yandex.eu": "yandex.ru",
    "yandex.az": "yandex.ru",
    "yandex.uz": "yandex.ru",
    "yandex.com.ge": "yandex.ru",
    # один Apple ID = один ящик на всех трёх доменах
    "me.com": "icloud.com",
    "mac.com": "icloud.com",
}


def normalize_email_identity(email: str) -> str:
    """Каноническая форма ящика: одинакова у всех адресов, письма на которые
    падают в один inbox. Это identity для анти-мультиакка, НЕ адрес доставки —
    письма шлём на введённый email, а сравниваем по этой форме.

    Правила: plus-тег отрезается у всех доменов (Gmail/Yandex/Mail.ru его
    поддерживают, у остальных «vasya+x» почти наверняка тот же владелец);
    Gmail игнорирует точки; Yandex считает «.» и «-» в логине взаимозаменяемыми.
    """
    e = (email or "").lower().strip()
    local, _, domain = e.partition("@")
    if not domain:
        return e
    domain = _DOMAIN_ALIASES.get(domain, domain)
    local = local.split("+", 1)[0]
    if domain == "gmail.com":
        local = local.replace(".", "")
    elif domain == "yandex.ru":
        local = local.replace(".", "-")
    return f"{local}@{domain}"


# Пепер книги триалов. НАМЕРЕННО литерал, а не secret_key: JWT-ключ ротируется
# по своим соображениям, и его смена молча обнулила бы всю книгу (хэши перестали
# бы совпадать — каждый бывший фермер получил бы свежий триал); alembic-процесс
# к тому же не гарантирует прод-env (ревью 14.07). Пепер против словарного
# перебора при сливе дампа БД: нужен ещё и код. НЕ МЕНЯТЬ после первого деплоя.
# Дубликат литерала живёт в миграции d4f7b9e1c5a8 (замороженный снапшот).
_TRIAL_BOOK_PEPPER = "baza-trial-book-v1"


def trial_identity_hash(email_identity: str) -> str:
    """Необратимый идентификатор для книги триалов (trial_grants).

    Переживает удаление аккаунта по ФЗ-152, не храня сам email, — повторная
    регистрация той же identity после удаления не получает второй триал.
    Вход ДОЛЖЕН быть результатом normalize_email_identity, иначе алиасы
    дадут разные хэши.
    """
    return hashlib.sha256(f"{_TRIAL_BOOK_PEPPER}:{email_identity}".encode()).hexdigest()


def trial_domain_hash(email: str) -> str:
    """Хэш ДОМЕНА почты для доменного потолка триалов (см. register()).

    Catch-all на собственном домене ($2/год + бесплатный форвардинг) даёт
    неограниченные «разные» ящики в один inbox — нормализация и верификация
    его не ловят (ревью 14.07). Потолок N триалов на некорпоративный домен
    делает ферму бессмысленной, не трогая честных: сотрудники одной компании
    объединяются в оргу по инвайту, а не N отдельными триалами.
    """
    domain = (email or "").lower().strip().rpartition("@")[2]
    domain = _DOMAIN_ALIASES.get(domain, domain)
    return hashlib.sha256(f"{_TRIAL_BOOK_PEPPER}:domain:{domain}".encode()).hexdigest()


# Массовые почтовые провайдеры: доменный потолок триалов к ним НЕ применяется
# (миллионы независимых владельцев ящиков; их фермерство ловит нормализация
# identity + верификация). Всё, что не здесь, считается «частным» доменом.
FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "yandex.ru", "mail.ru", "bk.ru", "list.ru", "inbox.ru",
    "internet.ru", "rambler.ru", "lenta.ru", "autorambler.ru", "myrambler.ru",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com",
    "yahoo.com", "aol.com", "protonmail.com", "proton.me", "pm.me",
    "tutanota.com", "tuta.io", "ukr.net", "i.ua", "meta.ua", "vk.com",
    # RFC-2606 зарезервированные: почта туда не доставляется, на проде такой
    # аккаунт не пройдёт верификацию; e2e-сьют же регистрирует ВСЁ на
    # example.com — без исключения доменный потолок душил бы тесты.
    "example.com", "example.org", "example.net",
})


def is_freemail_domain(email: str) -> bool:
    domain = (email or "").lower().strip().rpartition("@")[2]
    return _DOMAIN_ALIASES.get(domain, domain) in FREEMAIL_DOMAINS


def _extra_disposable_domains() -> frozenset[str]:
    raw = getattr(settings, "disposable_email_domains_extra", "") or ""
    return frozenset(d.strip().lower() for d in raw.split(",") if d.strip())


def is_disposable_email(email: str) -> bool:
    domain = (email or "").lower().strip().rpartition("@")[2]
    if not domain:
        return False
    blocked = _DISPOSABLE_DOMAINS | _extra_disposable_domains()
    if domain in blocked:
        return True
    # поддомены: abc123.mailinator.com и прочая ротация
    return any(domain.endswith("." + d) for d in blocked)


def _daily_cap() -> int:
    # В dev/тестах e2e-сьют регистрирует сотни оргов с одного «testclient» —
    # тот же приём, что _is_dev в main.py.
    if settings.app_env == "development":
        return 100_000
    return max(1, getattr(settings, "registration_attempts_per_ip_per_day", 10))


def _daily_key(ip: str) -> str:
    return f"reg_ip_daily:{ip}:{int(time.time()) // 86400}"


def ensure_registration_allowed(email: str, ip: str) -> None:
    """Поднимает 400 (одноразовая почта) или 429 (суточный потолок с IP).

    Считаются УСПЕШНЫЕ регистрации (note_successful_registration после
    коммита), а не попытки: за офисным NAT/мобильным CGNAT сидят тысячи
    честных людей, и опечатка с 409 не должна тратить их общий потолок
    (ревью 14.07). Разрыв check→increment даёт гонке параллельных
    регистраций небольшой перебор потолка — приемлемо: это скрипт-килер,
    а не точный лимит (burst и так зажат HTTP-tier'ом 10/мин в main.py).

    Redis-недоступность = fail-open (регистрация важнее лимита) — тот же
    компромисс, что в rate_limit_middleware.
    """
    if is_disposable_email(email):
        raise HTTPException(
            status_code=400,
            detail="Временные email-адреса не подходят — укажите рабочую или личную почту.",
        )
    try:
        current = int(_redis.get(_daily_key(ip)) or 0)
    except redis.exceptions.RedisError:
        logger.warning("registration guard: Redis unavailable, allowing", exc_info=True)
        return
    if current >= _daily_cap():
        logger.warning("registration guard: daily cap hit for ip=%s (%s registrations)", ip, current)
        raise HTTPException(
            status_code=429,
            detail="Слишком много регистраций с вашего адреса. Попробуйте завтра или напишите на support@usebaza.ru.",
        )


def note_successful_registration(ip: str) -> None:
    """Вызывается ПОСЛЕ успешного коммита регистрации (см. ensure_...)."""
    try:
        pipe = _redis.pipeline()
        pipe.incr(_daily_key(ip))
        pipe.expire(_daily_key(ip), 86400)
        pipe.execute()
    except redis.exceptions.RedisError:
        logger.warning("registration guard: Redis unavailable on note", exc_info=True)
