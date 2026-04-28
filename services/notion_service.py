import os
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv

load_dotenv()


class NotionServiceError(Exception):
    pass


@dataclass
class NotionCreatePageResult:
    page_id: str
    url: str
    raw_response: dict


class NotionService:
    NOTION_API_BASE = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self) -> None:
        self.token = (os.getenv("NOTION_TOKEN") or "").strip()
        self.database_id = (os.getenv("NOTION_DATABASE_ID") or "").strip()

        if not self.token:
            raise NotionServiceError("Не найден NOTION_TOKEN в .env")

        if not self.database_id:
            raise NotionServiceError("Не найден NOTION_DATABASE_ID в .env")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.NOTION_VERSION,
        }

    def _rich_text(self, text: str) -> list[dict]:
        text = (text or "").strip()
        if not text:
            return []

        return [
            {
                "type": "text",
                "text": {
                    "content": text[:2000],
                },
            }
        ]

    def _title_property(self, title: str) -> dict:
        return {
            "title": {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": title[:200],
                        },
                    }
                ]
            }
        }

    def _cover_payload(self, cover_url: str | None) -> dict | None:
        cover_url = (cover_url or "").strip()
        if not cover_url:
            return None

        return {
            "type": "external",
            "external": {
                "url": cover_url,
            },
        }

    def _icon_payload(self, emoji: str | None) -> dict | None:
        emoji = (emoji or "").strip()
        if not emoji:
            return None

        return {
            "type": "emoji",
            "emoji": emoji,
        }

    def _paragraph_block(self, text: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": self._rich_text(text),
            },
        }

    def _heading_block(self, text: str, level: int = 2) -> dict:
        block_type = {
            1: "heading_1",
            2: "heading_2",
            3: "heading_3",
        }.get(level, "heading_2")

        return {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": self._rich_text(text),
            },
        }

    def _bulleted_item_block(self, text: str) -> dict:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": self._rich_text(text),
            },
        }

    def _numbered_item_block(self, text: str) -> dict:
        return {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": self._rich_text(text),
            },
        }

    def _callout_block(self, text: str, emoji: str = "✨") -> dict:
        return {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {
                    "type": "emoji",
                    "emoji": emoji,
                },
                "rich_text": self._rich_text(text),
            },
        }

    def _quote_block(self, text: str) -> dict:
        return {
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": self._rich_text(text),
            },
        }

    def _divider_block(self) -> dict:
        return {
            "object": "block",
            "type": "divider",
            "divider": {},
        }

    def build_luxury_day_plan_blocks(
        self,
        *,
        intro: str,
        sections: list[dict],
        closing_note: str | None = None,
    ) -> list[dict]:
        blocks: list[dict] = []

        if intro.strip():
            blocks.append(self._callout_block(intro, emoji="☕"))
            blocks.append(self._divider_block())

        for index, section in enumerate(sections):
            title = (section.get("title") or "").strip()
            emoji = (section.get("emoji") or "").strip()
            lines = section.get("lines") or []
            note = (section.get("note") or "").strip()
            quote = (section.get("quote") or "").strip()
            style = (section.get("style") or "bulleted").strip().lower()

            heading_text = f"{emoji} {title}".strip() if emoji else title
            if heading_text:
                blocks.append(self._heading_block(heading_text, level=2))

            for line in lines:
                cleaned = (line or "").strip()
                if not cleaned:
                    continue

                if style == "numbered":
                    blocks.append(self._numbered_item_block(cleaned))
                else:
                    blocks.append(self._bulleted_item_block(cleaned))

            if note:
                blocks.append(self._callout_block(note, emoji=emoji or "✨"))

            if quote:
                blocks.append(self._quote_block(quote))

            if index != len(sections) - 1:
                blocks.append(self._divider_block())

        if closing_note and closing_note.strip():
            blocks.append(self._heading_block("🌙 Итог", level=2))
            blocks.append(self._paragraph_block(closing_note))

        return blocks

    async def create_page(
        self,
        *,
        title: str,
        intro: str,
        sections: list[dict],
        closing_note: str | None = None,
        icon_emoji: str | None = "✨",
        cover_url: str | None = None,
    ) -> NotionCreatePageResult:
        title = (title or "").strip()
        if not title:
            raise NotionServiceError("Пустой заголовок страницы")

        children = self.build_luxury_day_plan_blocks(
            intro=intro,
            sections=sections,
            closing_note=closing_note,
        )

        payload = {
            "parent": {
                "type": "database_id",
                "database_id": self.database_id,
            },
            "properties": self._title_property(title),
            "children": children,
        }

        icon_payload = self._icon_payload(icon_emoji)
        if icon_payload:
            payload["icon"] = icon_payload

        cover_payload = self._cover_payload(cover_url)
        if cover_payload:
            payload["cover"] = cover_payload

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.NOTION_API_BASE}/pages",
                json=payload,
                headers=self._build_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response_text = await response.text()

                if response.status not in (200, 201):
                    raise NotionServiceError(
                        f"Notion вернул ошибку при создании страницы: "
                        f"HTTP {response.status} | {response_text}"
                    )

                try:
                    data = await response.json()
                except Exception as exc:
                    raise NotionServiceError(
                        "Не удалось распарсить ответ Notion при создании страницы"
                    ) from exc

        page_id = (data.get("id") or "").strip()
        url = (data.get("url") or "").strip()

        if not page_id:
            raise NotionServiceError("Notion не вернул id страницы")

        if not url:
            raise NotionServiceError("Notion не вернул url страницы")

        return NotionCreatePageResult(
            page_id=page_id,
            url=url,
            raw_response=data,
        )

    async def smoke_test_day_plan_page(self) -> NotionCreatePageResult:
        return await self.create_page(
            title="Тест: день без развала",
            intro=(
                "Небольшая проверка интеграции. "
                "Если страница выглядит аккуратно — можно подключать реальный контент."
            ),
            sections=[
                {
                    "title": "Утро без развала",
                    "emoji": "☀️",
                    "lines": [
                        "Сначала поешь, потом спасай свою жизнь.",
                        "Не лезь в рилсы с утра. Там еще никому не стало легче.",
                        "Утром не надо быть красивой, продуктивной и просветленной одновременно. Выбери что-то одно.",
                    ],
                    "note": "Кофе плюс выйти из дома — уже терапия.",
                    "quote": "Иногда тебе нужен не знак свыше, а выйти за кофеечком.",
                },
                {
                    "title": "Главный фокус",
                    "emoji": "🎯",
                    "lines": [
                        "Не распыляйся. Ты не конфетти.",
                        "Выбери одну главную задачу. Остальное потом подползет к королеве на коленях.",
                        "Один закрытый кусок лучше, чем весь день страдать. Но если страдать — только красиво.",
                    ],
                    "note": "Мир переживет, если сегодня ты просто сделаешь одно дело нормально.",
                },
                {
                    "title": "Движение",
                    "emoji": "🚶‍♀️",
                    "lines": [
                        "Тебе нужен не подвиг. Тебе нужно подвигаться.",
                        "Тревожный кабанчик тоже должен гулять.",
                        "Двигаться надо не потому что “надо худеть”, а потому что ты не кактус.",
                    ],
                    "note": "Не нужно подвигов. Нужно, чтобы кровь вообще не забыла, как двигаться.",
                },
                {
                    "title": "Время под бота",
                    "emoji": "🤖",
                    "lines": [
                        "Не жди идеального состояния. Эта мадам может сильно задерживаться.",
                        "Не надо сначала “войти в ресурс”. В ресурс всегда заходят через дело.",
                        "Скоро увидишь, что сделано куда больше, чем было в твоей светлой головушке.",
                    ],
                    "note": "Ближайший шаг уже достаточно дерзок.",
                },
            ],
            closing_note="Не тащи день в ночь. Закрывай лавочку.",
            icon_emoji="💅",
            cover_url=None,
        )


async def create_notion_day_plan_page(
    *,
    title: str,
    intro: str,
    sections: list[dict],
    closing_note: str | None = None,
    icon_emoji: str | None = "✨",
    cover_url: str | None = None,
) -> NotionCreatePageResult:
    service = NotionService()
    return await service.create_page(
        title=title,
        intro=intro,
        sections=sections,
        closing_note=closing_note,
        icon_emoji=icon_emoji,
        cover_url=cover_url,
    )


async def smoke_test_notion_day_plan_page() -> NotionCreatePageResult:
    service = NotionService()
    return await service.smoke_test_day_plan_page()
