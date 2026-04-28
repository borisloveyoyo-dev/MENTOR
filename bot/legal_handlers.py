import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()
logger = logging.getLogger(__name__)

SUPPORT_BOT_URL = "https://t.me/ImpulseMentorSupport_bot"
LEGAL_DIR = Path("/opt/project/legal")
LEGAL_FILES = {
    "terms": LEGAL_DIR / "user_agreement.md",
    "privacy": LEGAL_DIR / "privacy_policy.md",
    "payments": LEGAL_DIR / "payments.md",
}

MAX_TELEGRAM_MESSAGE_LENGTH = 3900


async def _send_long_text(message: Message, text: str) -> None:
    clean_text = text.strip()
    if not clean_text:
        await message.answer("Документ пока пустой.")
        return

    chunks: list[str] = []
    current = ""

    for paragraph in clean_text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = paragraph
        else:
            for index in range(0, len(paragraph), MAX_TELEGRAM_MESSAGE_LENGTH):
                chunks.append(paragraph[index : index + MAX_TELEGRAM_MESSAGE_LENGTH])
            current = ""

    if current:
        chunks.append(current)

    for chunk in chunks:
        await message.answer(chunk)


async def _send_legal_document(message: Message, key: str, fallback_title: str) -> None:
    file_path = LEGAL_FILES[key]

    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("legal_file_missing key=%s path=%s", key, file_path)
        await message.answer(
            f"{fallback_title} пока не найден на сервере.\n\n"
            f"Напиши в поддержку: {SUPPORT_BOT_URL}"
        )
        return
    except Exception:
        logger.exception("legal_file_read_failed key=%s path=%s", key, file_path)
        await message.answer(
            "Не получилось открыть документ.\n\n"
            f"Напиши в поддержку: {SUPPORT_BOT_URL}"
        )
        return

    await _send_long_text(message, text)


@router.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    await _send_legal_document(message, "terms", "Пользовательское соглашение")


@router.message(Command("privacy"))
async def cmd_privacy(message: Message) -> None:
    await _send_legal_document(message, "privacy", "Политика конфиденциальности")


@router.message(Command("payments"))
async def cmd_payments(message: Message) -> None:
    await _send_legal_document(message, "payments", "Условия оплаты")


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    await message.answer(
        "Если что-то сломалось, не подошел формат, нужен возврат "
        "или хочешь оставить отзыв — напиши сюда:\n"
        f"{SUPPORT_BOT_URL}"
    )


@router.message(Command("refund"))
async def cmd_refund(message: Message) -> None:
    await message.answer(
        "Возврат можно запросить через поддержку.\n\n"
        "Напиши, пожалуйста, что произошло:\n"
        "— не подошел формат;\n"
        "— случайная оплата;\n"
        "— техническая проблема;\n"
        "— другое.\n\n"
        "После успешного возврата доступ к оплаченному периоду прекращается.\n\n"
        f"Поддержка: {SUPPORT_BOT_URL}"
    )
