import json
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import select

from db.database import async_session_maker
from db.models import User, UserProfile
from services.notion_service import (
    create_notion_day_plan_page,
)

load_dotenv()


class DayPlanServiceError(Exception):
    pass


@dataclass
class DayPlanGenerateResult:
    title: str
    intro: str
    sections: list[dict[str, Any]]
    closing_note: str
    raw_text: str


@dataclass
class DayPlanCreateForUserResult:
    user_id: int
    telegram_user_id: int
    page_title: str
    page_url: str
    page_id: str
    generated_plan: DayPlanGenerateResult


class DayPlanService:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL")

        if not api_key:
            raise DayPlanServiceError("Не найден OPENAI_API_KEY в .env")

        if not model:
            raise DayPlanServiceError("Не найден OPENAI_MODEL в .env")

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def create_personal_day_plan_page_for_telegram_user(
        self,
        *,
        telegram_user_id: int,
        cover_url: str | None = None,
    ) -> DayPlanCreateForUserResult:
        user, profile = await self._load_user_with_profile_by_telegram_id(telegram_user_id)

        generated_plan = await self.generate_day_plan_for_user(
            first_name=(user.first_name or "").strip(),
            current_income_source=profile.current_income_source,
            free_time_style=profile.free_time_style,
            appreciation_reason=profile.appreciation_reason,
            help_request_reason=profile.help_request_reason,
            about_text=profile.about_text,
            selected_direction=user.selected_direction,
        )

        notion_result = await create_notion_day_plan_page(
            title=generated_plan.title,
            intro=generated_plan.intro,
            sections=generated_plan.sections,
            closing_note=generated_plan.closing_note,
            icon_emoji="🌞",
            cover_url=cover_url,
        )

        return DayPlanCreateForUserResult(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            page_title=generated_plan.title,
            page_url=notion_result.url,
            page_id=notion_result.page_id,
            generated_plan=generated_plan,
        )

    async def generate_day_plan_for_user(
        self,
        *,
        first_name: str | None,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
        selected_direction: str | None,
    ) -> DayPlanGenerateResult:
        prompt = self._build_day_plan_prompt(
            first_name=first_name,
            current_income_source=current_income_source,
            free_time_style=free_time_style,
            appreciation_reason=appreciation_reason,
            help_request_reason=help_request_reason,
            about_text=about_text,
            selected_direction=selected_direction,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        raw_text = (response.output_text or "").strip()
        if not raw_text:
            raise DayPlanServiceError("OpenAI вернул пустой ответ по плану дня")

        parsed = self._parse_json_response(raw_text)

        title = self._normalize_required_string(parsed, "title")
        intro = self._normalize_required_string(parsed, "intro")
        sections = self._normalize_sections(parsed, "sections")
        closing_note = self._normalize_required_string(parsed, "closing_note")

        return DayPlanGenerateResult(
            title=title,
            intro=intro,
            sections=sections,
            closing_note=closing_note,
            raw_text=raw_text,
        )

    async def _load_user_with_profile_by_telegram_id(
        self,
        telegram_user_id: int,
    ) -> tuple[User, UserProfile]:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise DayPlanServiceError(
                    f"Пользователь с telegram_user_id={telegram_user_id} не найден"
                )

            profile_result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user.id)
            )
            profile = profile_result.scalar_one_or_none()

            if profile is None:
                raise DayPlanServiceError(
                    f"Профиль пользователя user_id={user.id} не найден"
                )

            return user, profile

    def _build_day_plan_prompt(
        self,
        *,
        first_name: str | None,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
        selected_direction: str | None,
    ) -> str:
        display_name = first_name.strip() if first_name and first_name.strip() else "пользователя"

        return f"""
Ты создаешь персональную Notion-страницу для нового пользователя Telegram-бота-наставника.

Твоя задача:
собрать УНИВЕРСАЛЬНЫЙ персональный распорядок дня, который можно использовать каждый день.
Это не план на один конкретный день и не список конкретных заданий.
Это удобный, повторяемый ритм дня для человека с его образом жизни.

Очень важно:
- страница должна быть про распорядок дня, хорошее самочувствие, движение и работу с ботом
- она должна опираться на онбординг
- если у человека работа / учеба / школа / институт / хаотичный график, это надо учитывать
- план должен быть проживаемым и реалистичным
- не делай жесткое расписание по минутам
- не делай из страницы сборник цитат
- не превращай блок про бота в конкретные задания
- конкретные задания человек будет получать в самом боте

Это НЕ:
- мотивационная статья
- коучинговый текст
- набор шуток
- распорядок по минутам
- план на конкретный день
- список заданий из бота

Это:
- короткий, внятный, реалистичный ежедневный ритм
- без перегруза
- с одним главным фокусом
- с движением / прогулкой
- со слотом под бота
- с вечерним завершением без самосуда

Тон:
- живой
- дерзкий
- человеческий
- емкий
- без воды
- без инфоцыганщины
- без дешевой "девочковости"
- не перегибай с юмором
- ощущение умной подруги с характером

Основа страницы:
используй последнюю емкую, дерзкую версию плана дня.
Нужен не поток фраз, а короткий полезный план.
Фразы-якоря используй точечно.

КРИТИЧЕСКИ ВАЖНО:
- НЕ придумывай новые "остроумные" фразы вне списка
- если нужен яркий акцент или финальная фраза, бери его ТОЛЬКО из утвержденного пула ниже
- closing_note должен звучать с характером, без пресного резюме
- closing_note не должен быть "правильным", сухим или коучинговым
- если уместно, closing_note может использовать одну из утвержденных фраз про вечер / ритм / базу
- юмор в конце должен быть легким, сухим и из вашего стиля, а не новым авторским стендапом модели

Структура страницы ОБЯЗАТЕЛЬНА:
1. Утро без рывка
2. Один главный фокус на день
3. Движение, чтобы не скиснуть
4. Время под бота
5. Вечернее завершение

Правила по блокам:

1. Утро без рывка
- 3–5 коротких действий
- помочь человеку спокойно войти в день
- еда, вода, не залипать с утра, оценить ресурс
- можно предложить выйти из дома / за кофе / на воздух
- это должен быть универсальный утренний вход в день

2. Один главный фокус на день
- 3–4 коротких пункта
- помочь человеку каждый день выбирать одну главную задачу
- не распыляться
- не делать огромный список дел
- это должен быть ежедневный принцип, а не задача на сегодня

3. Движение, чтобы не скиснуть
- 2–4 коротких пункта
- прогулка / гимнастика / разминка
- объяснить, что движение нужно не ради героизма, а чтобы голова не закисала
- это должен быть ежедневный блок самочувствия

4. Время под бота
- 3–4 коротких пункта
- встроить в день слот под бота
- не думать далеко вперед
- делать один кусок, не геройствовать
- не давать конкретных заданий
- можно сказать, что за 20 / 40 / 60 / 120 минут человек обычно успевает:
  - пройти один шаг
  - добить один кусок
  - спокойно разобраться с текущей задачей
  - продвинуться в выбранной тематике
- если выбранное направление есть, мягко учитывай его именно в этом блоке
- если направления нет, блок все равно должен работать универсально

5. Вечернее завершение
- 2–3 коротких пункта
- не жевать день по второму кругу
- 3 вопроса на вечер
- не добивать себя мыслями
- это должен быть ежедневный способ закрыть день
- здесь особенно уместны фразы из утвержденного пула про ночь / рутину / закрытие дня

Финал:
- closing_note на 2–4 предложения
- без пафоса
- ощущение: "такой день можно проживать каждый день"
- closing_note должен быть характерным и живым
- хотя бы одна фраза или интонация в closing_note должна быть из утвержденного стиля, а не нейтральной

Пул фраз-якорей.
Используй только если уместно. Не вставляй все подряд.
Максимум 1 яркая фраза на блок.

- Сначала поешь, потом спасай свою жизнь.
- Нельзя строить новый день на пустом желудке и нервной системе.
- Не лезь в рилсы с утра. Там еще никому не стало легче.
- Если день начался с телефона, попробуй хотя бы не заканчивать им свою самооценку.
- Утром не надо быть красивой, продуктивной и просветленной одновременно. Выбери что-то одно.
- Кофе — это хорошо. Кофе плюс выйти из дома — уже терапия.
- Иногда тебе нужен не знак свыше, а выйти за кофеечком.
- Если погодка хорошая, грех не выгулять себя хотя бы вокруг дома.
- Ты не ленивая. Возможно, ты просто не ела, не спала и задолбалась.
- Один закрытый кусок лучше, чем весь день страдать. Но если страдать — только красиво.
- Не распыляйся. Ты не конфетти.
- Чем больше дел ты хватаешь, тем выше шанс просто психануть и лечь.
- Выбери одну главную задачу. Остальное потом подползет к королеве на коленях.
- Мир переживет, если сегодня ты просто сделаешь одно дело нормально.
- Тебе нужен не подвиг. Тебе нужно подвигаться.
- Тревожный кабанчик тоже должен гулять.
- Не жди идеального состояния. Эта мадам может сильно задерживаться.
- Скоро увидишь, что сделано куда больше, чем было в твоей светлой головушке.
- Не надо сначала "войти в ресурс". В ресурс всегда заходят через дело.
- Не сожри себя мыслями под ночь.
- Сначала умойся, потом паникуй.
- Если ты поела — день уже пошел не по худшему сценарию.
- Если вышла из дома до обеда — уже есть за что себя уважать.
- Ты не бессмертная. Поесть надо.
- Нельзя делать серьезные выводы о жизни, пока не позавтракала.
- Не надо открывать день с тревоги, открой его хотя бы с еды.
- Не надо писать список задач, как будто у тебя три жизни и ассистент.
- Лучше сделать одну вещь нормально, чем восемь через нервный тик.
- Двигаться надо не потому что "надо худеть", а потому что ты не кактус.
- Прогуляйся. Голова сама чуть тише станет.
- Не нужно подвигов. Нужно, чтобы кровь вообще не забыла, как двигаться.
- Ты не обязана знать весь путь. Ближайший шаг уже достаточно дерзок.
- Не жди, пока у тебя появится "правильное настроение". Оно любит опаздывать.
- В ресурс всегда заходят через действие, а не через лежание с умным лицом.
- Не тащи день в ночь. Закрывай лавочку.

Данные пользователя:

Имя:
{display_name}

Как он сейчас живет / сколько у него времени:
{current_income_source or "Не указано"}

К чему его тянет:
{free_time_style or "Не указано"}

Что он уже пробовал:
{appreciation_reason or "Не указано"}

На что в себе может опереться:
{help_request_reason or "Не указано"}

Свободный рассказ о себе:
{about_text or "Не указано"}

Выбранное направление:
{selected_direction or "Пока не выбрано"}

Верни ответ СТРОГО в JSON.

Формат:
{{
  "title": "Короткий заголовок страницы",
  "intro": "Короткое вступление, 2-3 предложения",
  "sections": [
    {{
      "title": "Утро без рывка",
      "emoji": "☀️",
      "lines": [
        "Короткий пункт 1",
        "Короткий пункт 2",
        "Короткий пункт 3"
      ],
      "note": "Короткая заметка",
      "quote": "Необязательная яркая фраза ТОЛЬКО из списка"
    }},
    {{
      "title": "Один главный фокус на день",
      "emoji": "🎯",
      "lines": [
        "Короткий пункт 1",
        "Короткий пункт 2",
        "Короткий пункт 3"
      ],
      "note": "Короткая заметка",
      "quote": ""
    }},
    {{
      "title": "Движение, чтобы не скиснуть",
      "emoji": "🚶‍♀️",
      "lines": [
        "Короткий пункт 1",
        "Короткий пункт 2"
      ],
      "note": "Короткая заметка",
      "quote": ""
    }},
    {{
      "title": "Время под бота",
      "emoji": "🤖",
      "lines": [
        "Короткий пункт 1",
        "Короткий пункт 2",
        "Короткий пункт 3"
      ],
      "note": "Короткая заметка",
      "quote": ""
    }},
    {{
      "title": "Вечернее завершение",
      "emoji": "🌙",
      "lines": [
        "Короткий пункт 1",
        "Короткий пункт 2"
      ],
      "note": "Короткая заметка",
      "quote": "Необязательная яркая фраза ТОЛЬКО из списка"
    }}
  ],
  "closing_note": "Короткий финальный вывод с характером и в утвержденном стиле"
}}
""".strip()

    def _parse_json_response(self, raw_text: str) -> dict[str, Any]:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        cleaned = raw_text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        start_index = cleaned.find("{")
        end_index = cleaned.rfind("}")

        if start_index == -1 or end_index == -1 or end_index <= start_index:
            raise DayPlanServiceError("Не удалось выделить JSON из ответа OpenAI")

        json_text = cleaned[start_index:end_index + 1]

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise DayPlanServiceError(
                "OpenAI вернул ответ, который не удалось распарсить как JSON"
            ) from exc

    def _normalize_required_string(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key)

        if not isinstance(value, str):
            raise DayPlanServiceError(f"В ответе OpenAI нет корректного поля {key}")

        value = value.strip()
        if not value:
            raise DayPlanServiceError(f"Поле {key} пустое")

        return value

    def _normalize_sections(
        self,
        data: dict[str, Any],
        key: str,
    ) -> list[dict[str, Any]]:
        value = data.get(key)
        if not isinstance(value, list):
            raise DayPlanServiceError(f"В ответе OpenAI нет корректного списка {key}")

        normalized_sections: list[dict[str, Any]] = []

        for item in value:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            emoji = item.get("emoji")
            lines = item.get("lines")
            note = item.get("note")
            quote = item.get("quote")

            if not isinstance(title, str) or not title.strip():
                continue

            if not isinstance(emoji, str):
                emoji = "✨"

            if not isinstance(lines, list):
                lines = []

            normalized_lines: list[str] = []
            for line in lines:
                if isinstance(line, str) and line.strip():
                    normalized_lines.append(line.strip())

            if not normalized_lines:
                continue

            if not isinstance(note, str):
                note = ""

            if not isinstance(quote, str):
                quote = ""

            normalized_sections.append(
                {
                    "title": title.strip(),
                    "emoji": emoji.strip() or "✨",
                    "lines": normalized_lines[:5],
                    "note": note.strip(),
                    "quote": quote.strip(),
                }
            )

        if len(normalized_sections) < 5:
            raise DayPlanServiceError(
                "OpenAI вернул слишком мало корректных секций плана дня"
            )

        return normalized_sections[:5]


async def create_personal_day_plan_page_for_telegram_user(
    *,
    telegram_user_id: int,
    cover_url: str | None = None,
) -> DayPlanCreateForUserResult:
    service = DayPlanService()
    return await service.create_personal_day_plan_page_for_telegram_user(
        telegram_user_id=telegram_user_id,
        cover_url=cover_url,
    )
