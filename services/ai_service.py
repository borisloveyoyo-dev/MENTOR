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


@dataclass
class TaskReviewResult:
    review_status: str  # done / partial / not_done
    summary: str
    strengths: list[str]
    what_to_fix: list[str]
    next_step_mode: str  # harder / same / easier
    next_step_hint: str
    raw_text: str


@dataclass
class NextStepPlanResult:
    step_title: str
    step_description: str
    why_this_step: str
    how_to_do_it: list[str]
    recommended_tools: list[str]
    success_criteria: str
    raw_text: str


@dataclass
class MilestoneResult:
    milestone_text: str
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

    async def transcribe_voice_file(
        self,
        *,
        voice_file_path: str,
    ) -> str:
        try:
            with open(voice_file_path, "rb") as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio_file,
                )
        except Exception as exc:
            raise AIServiceError("Не удалось расшифровать голосовое") from exc

        text = (getattr(transcript, "text", None) or "").strip()
        if not text:
            raise AIServiceError("Расшифровка голосового получилась пустой")

        return text

    async def review_task_by_voice_transcript(
        self,
        *,
        selected_direction: str,
        task_title: str,
        task_description: str,
        voice_transcript: str,
    ) -> TaskReviewResult:
        prompt = self._build_voice_review_prompt(
            selected_direction=selected_direction,
            task_title=task_title,
            task_description=task_description,
            voice_transcript=voice_transcript,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        raw_text = (response.output_text or "").strip()
        if not raw_text:
            raise AIServiceError("OpenAI вернул пустой review по голосовому")

        parsed = self._parse_json_response(raw_text)
        return TaskReviewResult(
            review_status=self._normalize_review_status(parsed, "review_status"),
            summary=self._normalize_required_string(parsed, "summary"),
            strengths=self._normalize_required_string_list(parsed, "strengths", limit=4),
            what_to_fix=self._normalize_required_string_list(parsed, "what_to_fix", limit=4),
            next_step_mode=self._normalize_next_step_mode(parsed, "next_step_mode"),
            next_step_hint=self._normalize_required_string(parsed, "next_step_hint"),
            raw_text=raw_text,
        )

    async def review_task_by_photo_file(
        self,
        *,
        selected_direction: str,
        task_title: str,
        task_description: str,
        photo_file_url: str,
    ) -> TaskReviewResult:
        prompt = self._build_photo_review_prompt(
            selected_direction=selected_direction,
            task_title=task_title,
            task_description=task_description,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": photo_file_url,
                        },
                    ],
                }
            ],
        )

        raw_text = (response.output_text or "").strip()
        if not raw_text:
            raise AIServiceError("OpenAI вернул пустой review по фото")

        parsed = self._parse_json_response(raw_text)
        return TaskReviewResult(
            review_status=self._normalize_review_status(parsed, "review_status"),
            summary=self._normalize_required_string(parsed, "summary"),
            strengths=self._normalize_required_string_list(parsed, "strengths", limit=4),
            what_to_fix=self._normalize_required_string_list(parsed, "what_to_fix", limit=4),
            next_step_mode=self._normalize_next_step_mode(parsed, "next_step_mode"),
            next_step_hint=self._normalize_required_string(parsed, "next_step_hint"),
            raw_text=raw_text,
        )

    async def generate_next_step_plan(
        self,
        *,
        selected_direction: str,
        current_task_title: str,
        current_task_description: str,
        review_summary: str,
        strengths: list[str],
        what_to_fix: list[str],
        next_step_mode: str,
        next_step_hint: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> NextStepPlanResult:
        prompt = self._build_next_step_prompt(
            selected_direction=selected_direction,
            current_task_title=current_task_title,
            current_task_description=current_task_description,
            review_summary=review_summary,
            strengths=strengths,
            what_to_fix=what_to_fix,
            next_step_mode=next_step_mode,
            next_step_hint=next_step_hint,
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
            raise AIServiceError("OpenAI вернул пустой ответ по следующему шагу")

        parsed = self._parse_json_response(raw_text)
        return NextStepPlanResult(
            step_title=self._normalize_required_string(parsed, "step_title"),
            step_description=self._normalize_required_string(parsed, "step_description"),
            why_this_step=self._normalize_required_string(parsed, "why_this_step"),
            how_to_do_it=self._normalize_required_string_list(parsed, "how_to_do_it", limit=5),
            recommended_tools=self._normalize_required_string_list(parsed, "recommended_tools", limit=5),
            success_criteria=self._normalize_required_string(parsed, "success_criteria"),
            raw_text=raw_text,
        )

    async def generate_user_milestone(
        self,
        *,
        selected_direction: str,
        recent_progress_summary: str,
    ) -> MilestoneResult:
        prompt = self._build_milestone_prompt(
            selected_direction=selected_direction,
            recent_progress_summary=recent_progress_summary,
        )

        response = await self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        raw_text = (response.output_text or "").strip()
        if not raw_text:
            raise AIServiceError("OpenAI вернул пустой маяк")

        parsed = self._parse_json_response(raw_text)
        return MilestoneResult(
            milestone_text=self._normalize_required_string(parsed, "milestone_text"),
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
- это не карьерный консультант, не психолог и не генератор бизнес-идей;
- это живой наставник, который вытаскивает человека из ступора в действие;
- сначала важны интерес, действие, маленький результат и ритм;
- тему денег не надо продавливать рано;
- направления должны быть современными, понятными, с быстрым входом и видимым результатом;
- хорошо, если в деятельность можно зайти руками и потом при желании делать из нее контент.

Кто перед тобой:
- молодой человек, который может не понимать, чего хочет;
- может бояться выбрать не то;
- может сомневаться, что хватит времени, дисциплины, таланта или уверенности;
- часто это новичок с нуля.

Твоя задача:
1. посмотреть на анкету и увидеть 3-5 живых направлений роста;
2. не ставить диагнозов и не обещать успех;
3. не писать мотивационную воду;
4. писать коротко, по-человечески, уверенно и тепло, но без слащавости;
5. предлагать не абстрактные "сферы", а понятные точки входа;
6. не делать акцент на заработке;
7. названия направлений делать короткими, в 1-2 слова, чтобы они поместились на кнопки;
8. учитывать, что человеку нужен быстрый вход и понятный первый результат.

Анкета пользователя:

1. Сколько у него времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что он уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Верни ответ СТРОГО в JSON, без markdown, без пояснений до и после.

Формат:
{{
  "summary": "Короткий вывод на 2-4 предложения. По тону как живой наставник: по делу, по-человечески, уверенно.",
  "directions": [
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Коротко и понятно: что это за направление и почему оно может зайти именно этому человеку."
    }},
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Коротко и понятно."
    }}
  ]
}}
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

Очень важные правила:
- считай, что пользователь — новичок почти с нуля, если в анкете нет явных признаков уверенного опыта;
- не предполагай, что он знает профессиональные термины, инструменты, интерфейсы и процессы;
- старт должен быть быстрым, понятным и нестрашным;
- нужен не "проект", а первый живой проход руками;
- человеку надо быстро почувствовать: "я могу", а не "мне снова надо долго готовиться".

Контекст бота:
- бот говорит коротко, живо, по-человечески;
- бот может быть чуть дерзким, но не давит;
- бот не звучит как курс, карьерный консультант или инфоцыганский коуч;
- сначала не тема денег, а действие, маленький результат и ритм;
- через 5-7 дней у человека уже должен быть наблюдаемый результат.

Выбранное направление:
{selected_direction}

Анкета пользователя:

1. Сколько у него времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что он уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Твоя задача:
- предложить ОДИН первый шаг;
- шаг должен быть максимально простым, прикладным и нестрашным;
- шаг должен занимать примерно 5-20 минут, максимум около 30 минут;
- шаг должен давать маленький наблюдаемый результат;
- шаг должен быть буквально выполнимым руками;
- если нужен инструмент, сначала предложи самый простой и доступный;
- можно советовать конкретные бесплатные или простые сервисы и приложения;
- не предлагай сразу сделать продукт, найти клиентов, продавать, делать большой проект или собирать что-то сложное;
- не используй жаргон без крайней необходимости;
- не толкай человека в заработок на первом шаге;
- не советуй опасные, незаконные или сомнительные вещи.

Про short_perspective:
- это 1-2 коротких предложения о том, что может получиться в ближайшие 5-7 дней, если человек будет держать ритм;
- результат должен быть реальным, наблюдаемым и прикладным;
- можно мягко намекнуть, что этому уже можно искать практическое применение;
- нельзя обещать деньги, клиентов, профессию или быстрый успех;
- нельзя звучать пафосно.

Верни ответ СТРОГО в JSON, без markdown и без пояснений.

Формат:
{{
  "step_title": "Очень короткое название шага, 2-5 слов",
  "short_perspective": "1-2 коротких предложения про ближайшие 5-7 дней: реальный результат и очень мягкий намек на практическое применение.",
  "step_description": "Очень коротко и понятно: что человек делает сейчас. Без абстракции и без жаргона.",
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
""".strip()

    def _build_voice_review_prompt(
        self,
        *,
        selected_direction: str,
        task_title: str,
        task_description: str,
        voice_transcript: str,
    ) -> str:
        return f"""
Ты проверяешь выполненный шаг пользователя в Telegram-боте-наставнике.

Очень важная роль:
ты не школьный проверяющий и не технадзор.
Ты наставник.
Твоя задача — понять, вошел ли человек в нужное действие, что у него уже получилось и можно ли вести его дальше.

Выбранное направление:
{selected_direction}

Текущий шаг:
Название: {task_title}

Описание шага:
{task_description}

Расшифровка голосового пользователя:
{voice_transcript}

Главные правила оценки:
- не ищи буквальное совпадение по мелким деталям, если по смыслу человек уже сделал шаг;
- если человек уловил суть и реально вошел в действие, лучше ставить done или partial, а не рубить в not_done;
- false negative хуже, чем чуть более добрый зачет;
- оценивай не "идеально ли по ТЗ", а "двигает ли это человека туда, куда нужен шаг";
- не фантазируй и не приписывай того, чего нет в расшифровке;
- если данных мало, выбирай partial или not_done;
- если человек сделал по-своему, но суть поймал, это чаще partial или done;
- not_done ставь только если пользователь реально ушел мимо шага или из расшифровки не видно нужного действия вообще.

Как писать ответ:
- коротко, живо, по-человечески;
- без канцелярита, без техзадания, без школьного тона;
- можно с мягким юмором;
- если работа мимо, сначала все равно признай сам факт действия, если он есть;
- если есть за что зацепиться, сначала назови конкретный удачный кусок;
- не перечисляй длинные списки;
- summary максимум 2-4 коротких предложения;
- strengths и what_to_fix — короткие и конкретные;
- если что-то не засчитываешь, объясняй зачем был нужен шаг, а не просто что "не соответствует".

Логика статусов:
- done: шаг по смыслу выполнен, даже если есть шероховатости;
- partial: база уже есть, суть частично поймана, нужен короткий дожим;
- not_done: нужное действие не видно или пользователь ушел совсем в сторону.

Что писать:
- summary: короткий человеческий вывод
- strengths: 1-3 конкретных удачных наблюдения, если они есть
- what_to_fix: 0-3 конкретных вещи, только если они реально нужны
- next_step_mode:
  - harder, если можно идти дальше и немного усложнять
  - same, если нужен дожим на том же уровне
  - easier, если человек ушел мимо и надо вернуть в более простой кусок
- next_step_hint: один короткий и понятный следующий ход

Верни ответ СТРОГО в JSON.

Формат:
{{
  "review_status": "done или partial или not_done",
  "summary": "Короткий человеческий вывод",
  "strengths": [
    "Конкретно что уже получилось"
  ],
  "what_to_fix": [
    "Что еще реально надо добить"
  ],
  "next_step_mode": "harder или same или easier",
  "next_step_hint": "Один короткий понятный следующий ход"
}}
""".strip()

    def _build_photo_review_prompt(
        self,
        *,
        selected_direction: str,
        task_title: str,
        task_description: str,
    ) -> str:
        return f"""
Ты проверяешь выполненный шаг пользователя в Telegram-боте-наставнике по изображению.

Очень важная роль:
ты не школьный проверяющий и не технадзор.
Ты наставник.
Твоя задача — понять, вошел ли человек в нужное действие, что у него уже получилось и можно ли вести его дальше.

Выбранное направление:
{selected_direction}

Текущий шаг:
Название: {task_title}

Описание шага:
{task_description}

Главные правила оценки:
- не ищи буквальное совпадение по мелким деталям, если по смыслу человек уже сделал шаг;
- если на фото виден реальный результат и он близок к цели шага, лучше ставить done или partial, а не рубить в not_done;
- false negative хуже, чем чуть более добрый зачет;
- оценивай не "идеально ли соответствует", а "двигает ли это человека туда, куда нужен шаг";
- не фантазируй и не приписывай того, чего не видно;
- если по фото мало данных, чаще выбирай partial, а не придумывай резкий отказ;
- если человек сделал по-своему, но суть уловил, это чаще partial или done;
- not_done ставь только если в кадре реально не видно самого нужного действия или результата.

Как писать ответ:
- коротко, живо, по-человечески;
- без техзадания, без актов экспертизы, без школьного тона;
- можно с мягким юмором;
- если работа мимо, сначала все равно признай сам факт действия, если он есть;
- если есть за что зацепиться, сначала назови конкретный удачный кусок;
- не перечисляй длинные списки;
- summary максимум 2-4 коротких предложения;
- strengths и what_to_fix — короткие и конкретные;
- если что-то не засчитываешь, объясняй зачем был нужен шаг, а не просто почему фото "не соответствует".

Логика статусов:
- done: шаг по смыслу выполнен, даже если есть шероховатости;
- partial: база уже есть, суть частично поймана, нужен короткий дожим;
- not_done: в кадре не видно нужного действия или результата, либо фото совсем уводит в сторону.

Что писать:
- summary: короткий человеческий вывод
- strengths: 1-3 конкретных удачных наблюдения, если они есть
- what_to_fix: 0-3 конкретных вещи, только если они реально нужны
- next_step_mode:
  - harder, если можно идти дальше и немного усложнять
  - same, если нужен дожим на том же уровне
  - easier, если человек ушел мимо и надо вернуть в более простой кусок
- next_step_hint: один короткий и понятный следующий ход

Верни ответ СТРОГО в JSON.

Формат:
{{
  "review_status": "done или partial или not_done",
  "summary": "Короткий человеческий вывод",
  "strengths": [
    "Конкретно что получилось по тому, что видно"
  ],
  "what_to_fix": [
    "Что еще реально надо добить или что не подтверждено"
  ],
  "next_step_mode": "harder или same или easier",
  "next_step_hint": "Один короткий понятный следующий ход"
}}
""".strip()

    def _build_next_step_prompt(
        self,
        *,
        selected_direction: str,
        current_task_title: str,
        current_task_description: str,
        review_summary: str,
        strengths: list[str],
        what_to_fix: list[str],
        next_step_mode: str,
        next_step_hint: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> str:
        strengths_text = "\n".join(f"- {item}" for item in strengths) or "- Пока без явных сильных сторон"
        fix_text = "\n".join(f"- {item}" for item in what_to_fix) or "- Пока без явных замечаний"

        return f"""
Ты строишь СЛЕДУЮЩИЙ шаг для пользователя Telegram-бота-наставника.

Очень важные правила:
- это не первый шаг;
- следующий шаг должен опираться на уже проделанную работу;
- усложнение должно идти в той же деятельности и по той же оси навыка;
- не уводи человека в сторону;
- если mode = harder, шаг чуть сложнее предыдущего;
- если mode = same, шаг на том же уровне, но точнее;
- если mode = easier, шаг должен быть проще и уже;
- шаг все равно должен быть понятным, выполнимым и не перегруженным;
- человеку нужно сохранять ритм и ощущение "я могу", а не тонуть в сложности.

Выбранное направление:
{selected_direction}

Предыдущий шаг:
Название: {current_task_title}

Описание:
{current_task_description}

Что бот увидел по выполнению:
{review_summary}

Что получилось хорошо:
{strengths_text}

Что еще надо добить:
{fix_text}

Какой режим следующего шага:
{next_step_mode}

Подсказка по следующему ходу:
{next_step_hint}

Анкета пользователя:

1. Сколько у него времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Верни ответ СТРОГО в JSON.

Формат:
{{
  "step_title": "Очень короткое название шага, 2-5 слов",
  "step_description": "Коротко и очень понятно: что человек делает сейчас",
  "why_this_step": "Почему логично идти сюда именно после уже сделанного",
  "how_to_do_it": [
    "Очень простой шаг 1",
    "Очень простой шаг 2",
    "Очень простой шаг 3"
  ],
  "recommended_tools": [
    "Конкретный простой инструмент 1"
  ],
  "success_criteria": "Очень простой и наблюдаемый признак, что шаг сделан"
}}
""".strip()

    def _build_milestone_prompt(
        self,
        *,
        selected_direction: str,
        recent_progress_summary: str,
    ) -> str:
        return f"""
Ты пишешь короткий маяк для пользователя Telegram-бота-наставника.

Выбранное направление:
{selected_direction}

Что уже есть по недавнему прогрессу:
{recent_progress_summary}

Твоя задача:
- дать короткий ориентир на ближайшие несколько дней;
- это не дедлайн и не давление;
- это живой маяк, к чему мы идем следующим проходом;
- можно мягко намекнуть, что этому уже можно искать практическое применение;
- нельзя обещать деньги или успех.

Верни ответ СТРОГО в JSON.

Формат:
{{
  "milestone_text": "1-2 коротких предложения"
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

    def _normalize_review_status(self, data: dict[str, Any], key: str) -> str:
        value = self._normalize_required_string(data, key).lower()
        if value not in {"done", "partial", "not_done"}:
            raise AIServiceError(f"Поле {key} должно быть done, partial или not_done")
        return value

    def _normalize_next_step_mode(self, data: dict[str, Any], key: str) -> str:
        value = self._normalize_required_string(data, key).lower()
        if value not in {"harder", "same", "easier"}:
            raise AIServiceError(f"Поле {key} должно быть harder, same или easier")
        return value
