import base64
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import aiohttp
from dotenv import load_dotenv
from sqlalchemy import select

from db.database import async_session_maker
from db.models import Payment

load_dotenv()


FIRST_MONTH_PRICE_RUB = "149.00"
FIRST_MONTH_TARIFF_CODE = "monthly_first_149"
REGULAR_MONTHLY_TARIFF_CODE = "monthly_299"


class PaymentServiceError(Exception):
    pass


@dataclass
class PaymentCreateResult:
    payment_id: str
    status: str
    confirmation_url: str
    amount_value: str
    amount_currency: str
    raw_response: dict[str, Any]


@dataclass
class PaymentWebhookResult:
    event: str
    payment_id: str
    status: str
    paid: bool
    user_id: int | None
    tariff_code: str | None
    raw_notification: dict[str, Any]
    payment_data: dict[str, Any]


class PaymentService:
    ALLOWED_PAYMENT_EVENTS = {
        "payment.succeeded": "succeeded",
        "payment.waiting_for_capture": "waiting_for_capture",
        "payment.canceled": "canceled",
    }

    def __init__(self) -> None:
        self.shop_id = os.getenv("YKASSA_SHOP_ID") or os.getenv("YOOKASSA_SHOP_ID")
        self.api_key = os.getenv("YKASSA_API_KEY") or os.getenv("YOOKASSA_API_KEY")
        self.return_url = os.getenv("PAYMENT_RETURN_URL")
        self.webhook_url = os.getenv("YOOKASSA_WEBHOOK_URL")

        if not self.shop_id:
            raise PaymentServiceError("Не найден YKASSA_SHOP_ID или YOOKASSA_SHOP_ID в .env")

        if not self.api_key:
            raise PaymentServiceError("Не найден YKASSA_API_KEY или YOOKASSA_API_KEY в .env")

        if not self.return_url:
            raise PaymentServiceError("Не найден PAYMENT_RETURN_URL в .env")

        self.api_base_url = "https://api.yookassa.ru/v3"

    def _build_auth_header(self) -> str:
        token = f"{self.shop_id}:{self.api_key}".encode("utf-8")
        encoded = base64.b64encode(token).decode("utf-8")
        return f"Basic {encoded}"

    def _build_headers(self, *, with_idempotence: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": self._build_auth_header(),
            "Content-Type": "application/json",
        }

        if with_idempotence:
            headers["Idempotence-Key"] = str(uuid.uuid4())

        return headers

    def _normalize_amount(self, amount_rub: str | int | float | Decimal) -> str:
        try:
            value = Decimal(str(amount_rub)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except (InvalidOperation, ValueError) as exc:
            raise PaymentServiceError("Некорректная сумма платежа") from exc

        if value <= 0:
            raise PaymentServiceError("Сумма платежа должна быть больше нуля")

        return str(value)

    async def _has_successful_payment(self, user_id: int) -> bool:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Payment.id)
                .where(Payment.user_id == user_id)
                .where(Payment.status == "succeeded")
                .limit(1)
            )
            return result.scalar_one_or_none() is not None

    async def _resolve_payment_terms(
        self,
        *,
        user_id: int,
        amount_rub: str | int | float | Decimal,
        tariff_code: str,
    ) -> tuple[str, str]:
        normalized_amount = self._normalize_amount(amount_rub)

        if tariff_code != REGULAR_MONTHLY_TARIFF_CODE:
            return normalized_amount, tariff_code

        has_successful_payment = await self._has_successful_payment(user_id)
        if has_successful_payment:
            return normalized_amount, tariff_code

        return self._normalize_amount(FIRST_MONTH_PRICE_RUB), FIRST_MONTH_TARIFF_CODE

    async def create_payment(
        self,
        *,
        user_id: int,
        amount_rub: str | int | float | Decimal,
        description: str,
        tariff_code: str,
    ) -> PaymentCreateResult:
        amount_value, resolved_tariff_code = await self._resolve_payment_terms(
            user_id=user_id,
            amount_rub=amount_rub,
            tariff_code=tariff_code,
        )

        payload = {
            "amount": {
                "value": amount_value,
                "currency": "RUB",
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self.return_url,
            },
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "tariff_code": resolved_tariff_code,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_base_url}/payments",
                json=payload,
                headers=self._build_headers(with_idempotence=True),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response_text = await response.text()

                if response.status not in (200, 201):
                    raise PaymentServiceError(
                        f"YooKassa вернула ошибку при создании платежа: "
                        f"HTTP {response.status} | {response_text}"
                    )

                try:
                    data = await response.json()
                except Exception as exc:
                    raise PaymentServiceError(
                        "Не удалось распарсить ответ YooKassa при создании платежа"
                    ) from exc

        payment_id = (data.get("id") or "").strip()
        status = (data.get("status") or "").strip()
        amount = data.get("amount") or {}
        confirmation = data.get("confirmation") or {}
        confirmation_url = (confirmation.get("confirmation_url") or "").strip()
        amount_currency = (amount.get("currency") or "").strip()
        response_amount_value = (amount.get("value") or "").strip()

        if not payment_id:
            raise PaymentServiceError("YooKassa не вернула payment_id")

        if not confirmation_url:
            raise PaymentServiceError("YooKassa не вернула confirmation_url")

        return PaymentCreateResult(
            payment_id=payment_id,
            status=status,
            confirmation_url=confirmation_url,
            amount_value=response_amount_value or amount_value,
            amount_currency=amount_currency or "RUB",
            raw_response=data,
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        payment_id = payment_id.strip()
        if not payment_id:
            raise PaymentServiceError("Пустой payment_id")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_base_url}/payments/{payment_id}",
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response_text = await response.text()

                if response.status != 200:
                    raise PaymentServiceError(
                        f"YooKassa вернула ошибку при запросе платежа: "
                        f"HTTP {response.status} | {response_text}"
                    )

                try:
                    data = await response.json()
                except Exception as exc:
                    raise PaymentServiceError(
                        "Не удалось распарсить ответ YooKassa при запросе платежа"
                    ) from exc

        return data

    async def parse_webhook(self, notification: dict[str, Any]) -> PaymentWebhookResult:
        if not isinstance(notification, dict):
            raise PaymentServiceError("Webhook пришел не в формате JSON-объекта")

        event = str(notification.get("event") or "").strip()
        obj = notification.get("object")

        if not event:
            raise PaymentServiceError("В webhook нет поля event")

        if event not in self.ALLOWED_PAYMENT_EVENTS:
            raise PaymentServiceError(f"Неподдерживаемое событие webhook: {event}")

        if not isinstance(obj, dict):
            raise PaymentServiceError("В webhook нет корректного поля object")

        payment_id = str(obj.get("id") or "").strip()
        if not payment_id:
            raise PaymentServiceError("В webhook нет payment_id")

        payment_data = await self.get_payment(payment_id)

        api_payment_id = str(payment_data.get("id") or "").strip()
        if not api_payment_id:
            raise PaymentServiceError("YooKassa API не вернула payment_id")

        if api_payment_id != payment_id:
            raise PaymentServiceError("payment_id в webhook не совпадает с payment_id из YooKassa API")

        status = str(payment_data.get("status") or "").strip()
        expected_status = self.ALLOWED_PAYMENT_EVENTS[event]
        if status != expected_status:
            raise PaymentServiceError(
                f"Статус платежа {status!r} не соответствует событию {event!r}"
            )

        paid = bool(payment_data.get("paid") is True)

        if event == "payment.succeeded" and not paid:
            raise PaymentServiceError("Для payment.succeeded платеж должен быть paid=true")

        metadata = payment_data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        user_id_raw = metadata.get("user_id")
        tariff_code_raw = metadata.get("tariff_code")

        user_id: int | None = None
        if user_id_raw is not None:
            user_id_candidate = str(user_id_raw).strip()
            if user_id_candidate:
                try:
                    user_id = int(user_id_candidate)
                except ValueError:
                    raise PaymentServiceError("metadata.user_id должен быть целым числом")

        tariff_code = str(tariff_code_raw).strip() if tariff_code_raw is not None else None
        if tariff_code == "":
            tariff_code = None

        return PaymentWebhookResult(
            event=event,
            payment_id=payment_id,
            status=status,
            paid=paid,
            user_id=user_id,
            tariff_code=tariff_code,
            raw_notification=notification,
            payment_data=payment_data,
        )


async def create_payment_link(
    *,
    user_id: int,
    amount_rub: str | int | float | Decimal,
    description: str,
    tariff_code: str,
) -> PaymentCreateResult:
    service = PaymentService()
    return await service.create_payment(
        user_id=user_id,
        amount_rub=amount_rub,
        description=description,
        tariff_code=tariff_code,
    )


async def get_payment_info(payment_id: str) -> dict[str, Any]:
    service = PaymentService()
    return await service.get_payment(payment_id)


async def parse_yookassa_webhook(notification: dict[str, Any]) -> PaymentWebhookResult:
    service = PaymentService()
    return await service.parse_webhook(notification)
