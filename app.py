import logging
import os
from datetime import datetime, timedelta

from aiohttp import web
from dotenv import load_dotenv
from sqlalchemy import select

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.handlers import router
from db.database import async_session_maker
from db.models import Payment, Subscription
from services.payment_service import (
    PaymentServiceError,
    parse_yookassa_webhook,
)
from services.scheduler_service import SchedulerService

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def get_env_value(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана переменная окружения: {name}")
    return value


BOT_TOKEN = get_env_value("SOULMATEMENTOR_BOT_TOKEN")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
TELEGRAM_WEBHOOK_PATH = get_env_value("TELEGRAM_WEBHOOK_PATH")
TELEGRAM_WEBHOOK_URL = get_env_value("TELEGRAM_WEBHOOK_URL")
TELEGRAM_WEBHOOK_SECRET = get_env_value("TELEGRAM_WEBHOOK_SECRET")
YOOKASSA_WEBHOOK_PATH = get_env_value("YOOKASSA_WEBHOOK_PATH")


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
dp.include_router(router)

scheduler_service = SchedulerService(bot)


async def healthcheck(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "service": "soulmate-mentor-bot",
        }
    )


async def _apply_successful_payment(payment_id: str, user_id: int | None) -> None:
    async with async_session_maker() as session:
        payment_result = await session.execute(
            select(Payment).where(Payment.yookassa_payment_id == payment_id)
        )
        payment = payment_result.scalar_one_or_none()

        if payment is None:
            logger.info("payment_not_found payment_id=%s", payment_id)
            return

        if payment.status == "succeeded":
            logger.info("payment_already_processed payment_id=%s", payment_id)
            return

        payment.status = "succeeded"
        if payment.paid_at is None:
            payment.paid_at = datetime.utcnow()

        target_user_id = user_id or payment.user_id

        subscription_result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == target_user_id)
            .order_by(Subscription.ends_at.desc(), Subscription.id.desc())
        )
        subscription = subscription_result.scalars().first()

        now = datetime.utcnow()

        if subscription is None:
            subscription = Subscription(
                user_id=target_user_id,
                status="active",
                starts_at=now,
                ends_at=now + timedelta(days=30),
                trial_used=True,
            )
            session.add(subscription)
            logger.info("subscription_created user_id=%s", target_user_id)
        else:
            current_end = (
                subscription.ends_at
                if subscription.ends_at and subscription.ends_at > now
                else now
            )
            subscription.status = "active"
            subscription.starts_at = subscription.starts_at or now
            subscription.ends_at = current_end + timedelta(days=30)
            subscription.trial_used = True
            subscription.updated_at = now
            logger.info("subscription_extended user_id=%s", target_user_id)

        await session.commit()


async def yookassa_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        logger.exception("yookassa_invalid_json")
        return web.json_response(
            {"status": "error", "message": "invalid json"},
            status=400,
        )

    try:
        webhook_result = await parse_yookassa_webhook(data)
    except PaymentServiceError as exc:
        logger.exception("yookassa_parse_error error=%s", exc)
        return web.json_response(
            {"status": "error", "message": str(exc)},
            status=400,
        )
    except Exception:
        logger.exception("yookassa_unexpected_parse_error")
        return web.json_response(
            {"status": "error", "message": "internal error"},
            status=500,
        )

    try:
        if webhook_result.event == "payment.succeeded" and webhook_result.paid:
            await _apply_successful_payment(
                payment_id=webhook_result.payment_id,
                user_id=webhook_result.user_id,
            )
        elif webhook_result.event in {"payment.waiting_for_capture", "payment.pending"}:
            async with async_session_maker() as session:
                payment_result = await session.execute(
                    select(Payment).where(
                        Payment.yookassa_payment_id == webhook_result.payment_id
                    )
                )
                payment = payment_result.scalar_one_or_none()

                if payment is not None and payment.status != "succeeded":
                    payment.status = webhook_result.status or "pending"
                    await session.commit()
        elif webhook_result.event == "payment.canceled":
            async with async_session_maker() as session:
                payment_result = await session.execute(
                    select(Payment).where(
                        Payment.yookassa_payment_id == webhook_result.payment_id
                    )
                )
                payment = payment_result.scalar_one_or_none()

                if payment is not None and payment.status != "succeeded":
                    payment.status = "canceled"
                    await session.commit()
    except Exception:
        logger.exception("yookassa_db_update_error")
        return web.json_response(
            {"status": "error", "message": "db update error"},
            status=500,
        )

    return web.json_response({"status": "ok"})


async def on_startup() -> None:
    allowed_updates = dp.resolve_used_update_types()

    logger.info("app_startup_begin")
    logger.info("webhook_path=%s", TELEGRAM_WEBHOOK_PATH)
    logger.info("webhook_url=%s", TELEGRAM_WEBHOOK_URL)
    logger.info("webhook_secret_enabled=%s", bool(TELEGRAM_WEBHOOK_SECRET))
    logger.info("allowed_updates=%s", allowed_updates)

    await bot.set_my_commands(
        [
            BotCommand(command="done", description="Сделал шаг"),
            BotCommand(command="stuck", description="Я завис"),
            BotCommand(command="easier", description="Сделай проще"),
            BotCommand(command="next", description="Дальше"),
            BotCommand(command="delete_me", description="Удалить мои данные"),
        ]
    )

    await bot.set_webhook(
        url=TELEGRAM_WEBHOOK_URL,
        allowed_updates=allowed_updates,
        secret_token=TELEGRAM_WEBHOOK_SECRET,
    )

    await scheduler_service.start()

    me = await bot.get_me()
    logger.info(
        "telegram_webhook_set username=%s webhook_url=%s",
        me.username,
        TELEGRAM_WEBHOOK_URL,
    )
    logger.info("scheduler_service_started")


async def on_shutdown() -> None:
    logger.info("app_shutdown_begin")
    await scheduler_service.stop()
    await bot.session.close()
    logger.info("app_shutdown_done")


def create_app() -> web.Application:
    app = web.Application()

    app.router.add_get("/health", healthcheck)
    app.router.add_post(YOOKASSA_WEBHOOK_PATH, yookassa_webhook)

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=TELEGRAM_WEBHOOK_SECRET,
    )
    webhook_requests_handler.register(app, path=TELEGRAM_WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    app.on_startup.append(lambda app: on_startup())
    app.on_shutdown.append(lambda app: on_shutdown())

    logger.info("aiohttp_app_created")
    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("web_run_app host=%s port=%s", APP_HOST, APP_PORT)
    web.run_app(app, host=APP_HOST, port=APP_PORT)
