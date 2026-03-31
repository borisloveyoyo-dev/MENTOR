import json
import os
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI


@dataclass
class DirectionOption:
    title: str
    description: str


@dataclass
class ProfileAnalysisResult:
    summary: str
    directions: list[DirectionOption]
    raw_text: str


@dataclass
class FirstStepPlanResult:
    step_title: str
    short_perspective: str
    step_description: str
    why_this_step: str
    how_to_do_it: list[str]
    recommended_tools: list[str]
    success_criteria: str
    raw_text: str


class AIServiceError(Exception):
    pass


class AIService:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL")

        if not api_key:
            raise AIServiceError("Не найден OPENAI_API_KEY в .env")

        if not model:
            raise AIServiceError("Не найден OPENAI_MODEL в .env")

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def analyze_user_profile(
        self,
        *,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> ProfileAnalysisResult:
        prompt = self._build_profile_analysis_prompt(
            current_income_source=current_income_source,
            free_time_style=free_time_style,
            appreciation_reason=appreciation_reason,
            help_request_reason=help_request_reason,
            about_text=about_text,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        raw_text = (response.output_text or "").strip()

        if not raw_text:
            raise AIServiceError("OpenAI вернул пустой ответ")

        parsed = self._parse_json_response(raw_text)

        summary = self._normalize_required_string(parsed, "summary")
        directions = self._normalize_direction_list(parsed, "directions", limit=5)

        if len(directions) < 3:
            raise AIServiceError("OpenAI вернул слишком мало направлений")

        return ProfileAnalysisResult(
            summary=summary,
            directions=directions,
            raw_text=raw_text,
        )

    async def generate_first_step_plan(
        self,
        *,
        selected_direction: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> FirstStepPlanResult:
        prompt = self._build_first_step_prompt(
            selected_direction=selected_direction,
            current_income_source=current_income_source,
            free_time_style=free_time_style,
            appreciation_reason=appreciation_reason,
            help_request_reason=help_request_reason,
            about_text=about_text,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        raw_text = (response.output_text or "").strip()

        if not raw_text:
            raise AIServiceError("OpenAI вернул пустой ответ по первому шагу")

        parsed = self._parse_json_response(raw_text)

        return FirstStepPlanResult(
            step_title=self._normalize_required_string(parsed, "step_title"),
            short_perspective=self._normalize_required_string(parsed, "short_perspective"),
            step_description=self._normalize_required_string(parsed, "step_description"),
            why_this_step=self._normalize_required_string(parsed, "why_this_step"),
            how_to_do_it=self._normalize_required_string_list(parsed, "how_to_do_it", limit=5),
            recommended_tools=self._normalize_required_string_list(parsed, "recommended_tools", limit=5),
            success_criteria=self._normalize_required_string(parsed, "success_criteria"),
            raw_text=raw_text,
        )

    def _build_profile_analysis_prompt(
        self,
        *,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> str:
        return f"""
Ты помогаешь Telegram-боту-наставнику для молодой аудитории.

Контекст бота:
- это не карьерный консультант и не генератор бизнес-идей;
- это живая, спокойная и человеческая опора;
- бот помогает человеку понять, куда ему может быть интересно расти;
- бот мягко ведет к маленьким реальным шагам;
- тему заработка НЕ надо продавливать рано;
- сначала важнее интерес, ощущение "у меня может получиться", маленький результат и ритм.

Кто перед тобой:
- молодой человек, который может не понимать, чего хочет;
- может бояться пробовать;
- может сомневаться, что хватит таланта, времени, денег или уверенности.

Твоя задача:
1. посмотреть на анкету и увидеть 3-5 живых направлений роста;
2. не ставить диагнозов и не обещать успех;
3. не писать мотивационную воду;
4. писать коротко, по-человечески, тепло, но без слащавости;
5. предлагать не абстрактные "сферы", а понятные точки входа;
6. не делать акцент на заработке;
7. названия направлений делать короткими, в 1-2 слова, чтобы они поместились на кнопки.

Анкета пользователя:

1. Чем сейчас зарабатывает:
{current_income_source or "Не указано"}

2. Как проводит свободное время:
{free_time_style or "Не указано"}

3. За что его благодарят или ценят:
{appreciation_reason or "Не указано"}

4. С чем к нему обращаются за помощью:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Верни ответ СТРОГО в JSON, без markdown, без пояснений до и после.

Формат:
{{
  "summary": "Короткий вывод на 2-4 предложения. По тону как живой наставник: спокойно, по делу, по-человечески.",
  "directions": [
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Короткое понятное описание: что это за направление и почему оно может подойти именно этому человеку."
    }},
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Короткое понятное описание."
    }}
  ]
}}

Правила к полю summary:
- 2-4 коротких предложения;
- можно использовать живые заходы вроде "Слушай", "Мне кажется", "Тут есть";
- без канцелярита;
- без давления;
- без пустой похвалы;
- не использовать пафос.

Правила к полю directions:
- от 3 до 5 объектов;
- title: короткий, понятный, 1-2 слова;
- title не должен быть слишком общим вроде "Развитие" или "Успех";
- description: 1-2 коротких предложения;
- description должна объяснять, почему это живой вариант именно для этого человека;
- не пиши про монетизацию как главный акцент;
- не превращай это в список профессий из воздуха;
- не используй формулировки в стиле "создай бизнес", "запусти проект", если в анкете для этого нет явной базы.
""".strip()

    def _build_first_step_prompt(
        self,
        *,
        selected_direction: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> str:
        return f"""
Ты помогаешь Telegram-боту-наставнику дать человеку первый шаг после выбора направления.

Это ОЧЕНЬ важное правило:
считай, что пользователь — новичок почти с нуля, если в анкете нет явных признаков уверенного опыта.
Не предполагай, что он знает профессиональные термины, инструменты, интерфейсы и рабочие процессы.

Контекст бота:
- бот говорит коротко, живо и по-человечески;
- бот не звучит как курс, карьерный консультант или инфоцыганский коуч;
- бот не давит;
- бот не тащит человека сразу в тему денег;
- бот помогает войти в действие руками;
- сначала нужен не амбициозный результат, а простой вход в работу;
- сначала не "мини-проект", а очень понятный первый контакт с делом;
- бот должен разжевывать старт предельно просто.

Выбранное направление:
{selected_direction}

Анкета пользователя:

1. Чем сейчас зарабатывает:
{current_income_source or "Не указано"}

2. Как проводит свободное время:
{free_time_style or "Не указано"}

3. За что его благодарят или ценят:
{appreciation_reason or "Не указано"}

4. С чем к нему обращаются за помощью:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Твоя задача:
- предложить ОДИН первый шаг;
- этот шаг должен быть максимально простым, прикладным и нестрашным;
- шаг должен быть рассчитан на новичка;
- шаг должен занимать примерно 5-20 минут, максимум около 30 минут;
- шаг должен давать маленький наблюдаемый результат;
- шаг должен быть не абстрактным, а буквально выполнимым руками;
- если нужен инструмент, сначала предложи самый простой и доступный;
- можно советовать конкретные бесплатные или простые сервисы и приложения;
- не предлагай сразу "сделать проект", "собрать продукт", "найти клиентов", "создать контент-план", "разработать концепцию", "смонтировать ролик", если это звучит как задача для уже понимающего человека;
- не используй профессиональный жаргон без крайней необходимости;
- не толкай человека в заработок на первом шаге;
- не советуй опасные, незаконные или сомнительные вещи.

Дополнительно нужен короткий блок short_perspective:
- это перспектива на ближайшие 5-7 дней, если человек будет держать ритм;
- там должен быть реальный, наблюдаемый, прикладной результат;
- формулировка должна быть живой и весомой, но реалистичной;
- можно очень мягко намекнуть, что этому уже можно искать практическое применение;
- нельзя обещать деньги, клиентов, заказы, профессию или быстрый заработок;
- нельзя звучать как продавец успеха;
- нельзя писать пафосно или абстрактно.

Главный принцип:
первый шаг должен выглядеть так, будто живой наставник сидит рядом и ведет человека за руку.
Не давай указания уровня "сделай монтаж", "собери карточки", "оформи концепт".
Давай указания уровня:
- скачай вот это приложение;
- открой его;
- нажми вот сюда;
- выбери любой файл;
- сделай одно простое действие;
- сохрани результат;
- потом напиши, где было непонятно.

Что НЕ подходит:
- абстрактные задания;
- слишком творческие или широкие формулировки без входа;
- задания, где пользователь уже должен уметь работать в инструменте;
- фразы, которые звучат как будто человек уже в теме;
- большие проекты.

Что подходит:
- установка и первый запуск простого инструмента;
- один элементарный заход в интерфейс;
- одна очень простая манипуляция;
- маленький черновой результат;
- понятный критерий "сделано".

Верни ответ СТРОГО в JSON, без markdown и без пояснений.

Формат:
{{
  "step_title": "Очень короткое название шага, 2-5 слов",
  "short_perspective": "1-2 коротких предложения про ближайшие 5-7 дней: реальный результат и очень мягкий намек, что этому уже можно искать практическое применение.",
  "step_description": "Коротко и очень понятно: что человек делает сейчас. Без абстракции и без жаргона.",
  "why_this_step": "Коротко объясни, почему начинаем именно так. По-человечески и без пафоса.",
  "how_to_do_it": [
    "Очень простой шаг 1",
    "Очень простой шаг 2",
    "Очень простой шаг 3",
    "Очень простой шаг 4"
  ],
  "recommended_tools": [
    "Конкретный простой инструмент 1",
    "Конкретный простой инструмент 2"
  ],
  "success_criteria": "Очень простой и наблюдаемый признак, что шаг сделан"
}}

Жесткие правила к ответу:
- step_title: короткий и конкретный;
- short_perspective: 1-2 коротких предложения;
- short_perspective должна описывать только ближайшие 5-7 дней;
- short_perspective должна давать реальный маленький, но весомый результат;
- в short_perspective допустим только мягкий намек в духе "этому уже можно искать практическое применение";
- short_perspective не должна обещать заработок, продажу, клиентов, монетизацию или успех;
- step_description: 1-2 коротких предложения;
- why_this_step: 1-2 коротких предложения;
- how_to_do_it: от 3 до 5 шагов;
- каждый пункт how_to_do_it должен быть написан так, будто это поймет человек вообще без опыта;
- каждый пункт how_to_do_it должен быть конкретным действием, а не общим советом;
- recommended_tools: от 1 до 3 пунктов;
- советуй по возможности бесплатные, простые и массово доступные инструменты;
- success_criteria должен описывать простой видимый результат;
- не пиши длинно;
- не пиши мотивационную воду;
- не пиши "исследуй", "продумай", "определи", "создай стратегию", "оформи концепцию";
- не предлагай большой творческий результат там, где сначала нужен вход в инструмент;
- если направление связано с цифровым инструментом, первый шаг почти всегда должен начинаться с установки, открытия или самого простого действия внутри него;
- если направление не цифровое, первый шаг должен быть предельно бытовым, понятным и выполнимым из подручных средств.
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
            raise AIServiceError("Не удалось выделить JSON из ответа OpenAI")

        json_text = cleaned[start_index:end_index + 1]

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise AIServiceError("OpenAI вернул ответ, который не удалось распарсить как JSON") from exc

    def _normalize_required_string(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key)

        if not isinstance(value, str):
            raise AIServiceError(f"В ответе OpenAI нет корректного поля {key}")

        value = value.strip()
        if not value:
            raise AIServiceError(f"Поле {key} пустое")

        return value

    def _normalize_required_string_list(
        self,
        data: dict[str, Any],
        key: str,
        *,
        limit: int,
    ) -> list[str]:
        value = data.get(key)

        if not isinstance(value, list):
            raise AIServiceError(f"В ответе OpenAI нет корректного списка {key}")

        result: list[str] = []

        for item in value:
            if not isinstance(item, str):
                continue

            item = item.strip()
            if item:
                result.append(item)

        return result[:limit]

    def _normalize_direction_list(
        self,
        data: dict[str, Any],
        key: str,
        *,
        limit: int,
    ) -> list[DirectionOption]:
        value = data.get(key)

        if not isinstance(value, list):
            raise AIServiceError(f"В ответе OpenAI нет корректного списка {key}")

        result: list[DirectionOption] = []

        for item in value:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            description = item.get("description")

            if not isinstance(title, str) or not isinstance(description, str):
                continue

            title = title.strip()
            description = description.strip()

            if not title or not description:
                continue

            result.append(
                DirectionOption(
                    title=title,
                    description=description,
                )
            )

        return result[:limit]
