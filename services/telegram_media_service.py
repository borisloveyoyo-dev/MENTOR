from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from aiogram import Bot


@dataclass
class TelegramPhotoPayload:
    file_id: str
    file_path: str
    file_url: str


@dataclass
class TelegramVoicePayload:
    file_id: str
    file_path: str
    local_path: str


class TelegramMediaServiceError(Exception):
    pass


class TelegramMediaService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def prepare_photo_for_review(self, *, file_id: str) -> TelegramPhotoPayload:
        if not file_id.strip():
            raise TelegramMediaServiceError("Пустой file_id для фото")

        try:
            telegram_file = await self.bot.get_file(file_id)
        except Exception as exc:
            raise TelegramMediaServiceError("Не удалось получить фото из Telegram") from exc

        file_path = (telegram_file.file_path or "").strip()
        if not file_path:
            raise TelegramMediaServiceError("Telegram не вернул file_path для фото")

        token = self.bot.token
        file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

        return TelegramPhotoPayload(
            file_id=file_id,
            file_path=file_path,
            file_url=file_url,
        )

    async def prepare_voice_for_review(self, *, file_id: str) -> TelegramVoicePayload:
        if not file_id.strip():
            raise TelegramMediaServiceError("Пустой file_id для голосового")

        try:
            telegram_file = await self.bot.get_file(file_id)
        except Exception as exc:
            raise TelegramMediaServiceError("Не удалось получить голосовое из Telegram") from exc

        file_path = (telegram_file.file_path or "").strip()
        if not file_path:
            raise TelegramMediaServiceError("Telegram не вернул file_path для голосового")

        suffix = os.path.splitext(file_path)[1] or ".ogg"

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                local_path = temp_file.name

            await self.bot.download_file(file_path, destination=local_path)
        except Exception as exc:
            try:
                if "local_path" in locals() and os.path.exists(local_path):
                    os.remove(local_path)
            except Exception:
                pass
            raise TelegramMediaServiceError("Не удалось скачать голосовое из Telegram") from exc

        return TelegramVoicePayload(
            file_id=file_id,
            file_path=file_path,
            local_path=local_path,
        )

    def cleanup_local_file(self, local_path: str | None) -> None:
        if not local_path:
            return

        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass


async def prepare_photo_file_for_review(bot: Bot, *, file_id: str) -> TelegramPhotoPayload:
    service = TelegramMediaService(bot)
    return await service.prepare_photo_for_review(file_id=file_id)


async def prepare_voice_file_for_review(bot: Bot, *, file_id: str) -> TelegramVoicePayload:
    service = TelegramMediaService(bot)
    return await service.prepare_voice_for_review(file_id=file_id)


def cleanup_downloaded_file(local_path: str | None) -> None:
    service = TelegramMediaService.__new__(TelegramMediaService)
    service.cleanup_local_file(local_path)
