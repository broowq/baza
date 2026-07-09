"""Приём клиентских JS-ошибок (наблюдаемость «Что-то пошло не так»).

Мотивация (кейс ЗАО «Бе щеки», 09.07.2026): пользователь стабильно ловил
error-boundary на /dashboard/settings, а мы были слепы — все API отвечали 200,
чанки отдавались, headless-репродукция под копией его аккаунта рендерилась.
Краш жил только в его браузере (перевод/расширение/битые данные сайта), и
диагностировать пришлось вслепую. Этот эндпоинт делает такие инциденты
видимыми: ErrorBoundary шлёт сюда стек, мы читаем его в логах backend.

Сознательно МИНИМАЛЬНЫЙ: только логирование (docker logs), без БД и без
аутентификации (ошибки случаются и у разлогиненных). Защита: жёсткий
rate-limit тир в app.main (5/мин с IP) + обрезка полей по длине.
"""
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/client-errors", tags=["observability"])
logger = logging.getLogger("client_errors")


class ClientErrorReport(BaseModel):
    message: str = Field(max_length=1000)
    stack: str = Field(default="", max_length=6000)
    component_stack: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=500)
    # Короткий код ошибки, который UI показывает пользователю («Код: ab12cd»)
    # — по нему саппорт находит эту запись в логах.
    error_id: str = Field(default="", max_length=16)


@router.post("", status_code=204)
def report_client_error(payload: ClientErrorReport, request: Request):
    client_ip = request.headers.get("X-Real-IP") or (
        request.client.host if request.client else "unknown"
    )
    ua = (request.headers.get("User-Agent") or "")[:300]
    logger.error(
        "CLIENT ERROR [%s] url=%s ip=%s ua=%s\nmessage: %s\nstack: %s\ncomponent_stack: %s",
        payload.error_id or "-",
        payload.url,
        client_ip,
        ua,
        payload.message,
        payload.stack,
        payload.component_stack,
    )
    # 204: репортер fire-and-forget, телу ответа некуда попадать.
    return None
