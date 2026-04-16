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


@dataclass
class DirectionFitReasonResult:
    fit_reason: str
    raw_text: str


@dataclass
class ChatReplyResult:
    reply: str
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
            how_to_do_it=self._normalize_required_string_list(parsed, "how_to_do_it", limit=6),
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
            how_to_do_it=self._normalize_required_string_list(parsed, "how_to_do_it", limit=6),
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

    async def explain_direction_fit(
        self,
        *,
        selected_direction: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> DirectionFitReasonResult:
        prompt = self._build_direction_fit_prompt(
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
            raise AIServiceError("OpenAI вернул пустое обоснование направления")

        parsed = self._parse_json_response(raw_text)
        return DirectionFitReasonResult(
            fit_reason=self._normalize_required_string(parsed, "fit_reason"),
            raw_text=raw_text,
        )

    async def generate_chat_reply(
        self,
        *,
        selected_direction: str | None,
        task_title: str | None,
        task_description: str | None,
        user_message: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> ChatReplyResult:
        prompt = self._build_chat_reply_prompt(
            selected_direction=selected_direction,
            task_title=task_title,
            task_description=task_description,
            user_message=user_message,
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
            raise AIServiceError("OpenAI вернул пустой чат-ответ")

        parsed = self._parse_json_response(raw_text)
        return ChatReplyResult(
            reply=self._normalize_required_string(parsed, "reply"),
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
- это живой наставник, который вытаскивает человека из ступора в действие;
- сначала важны интерес, действие, маленький результат и ритм;
- не делай из ответа карьерную консультацию, психологический портрет или продажу профессии;
- названия направлений должны быть короткими и понятными;
- описание направлений должно быть живым и конкретным.

Кто перед тобой:
- новичок почти с нуля, если нет явных признаков опыта;
- может бояться выбрать не то;
- может сомневаться в себе;
- может не уметь точно формулировать, чего хочет.

Твоя задача:
1. увидеть 3-5 живых направлений;
2. не писать воду;
3. не делать пафос;
4. не делать обоснование через "легкий вход", "несложно", "быстро", "удобно";
5. причина, почему направление подходит, должна быть именно про человека и его ответы;
6. если ответ косвенный или слабый, все равно выведи внятную человеческую причину из анкеты;
7. не используй абстрактные и мутные слова.

Анкета пользователя:

1. Сколько у него свободного времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что он уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Верни ответ СТРОГО в JSON, без markdown, без пояснений.

Формат:
{{
  "summary": "Короткий вывод на 2-4 предложения. Живой, уверенный, без воды.",
  "directions": [
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Почему это направление подходит именно этому человеку по его анкете. Коротко, живо и конкретно."
    }},
    {{
      "title": "Короткое название в 1-2 слова",
      "description": "Коротко и конкретно."
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

Критически важно:
- считай, что пользователь полный новичок, пока в анкете нет прямых признаков, что он умеет больше;
- пользователь не знает терминов, интерфейсов, процессов и последовательностей, пока ты не объяснил это прямо;
- если ты предлагаешь действие, сразу объясни, как его сделать буквально;
- если ты пишешь "скачай", сразу объясни, где искать и что нажать;
- если ты пишешь "создай папку", сразу объясни, как именно ее создать;
- если ты пишешь "открой сервис", сразу объясни, где он находится и что делать после открытия;
- никакой абстракции и догадок от пользователя.

Очень важные правила:
- первый шаг должен быть маленьким, конкретным и психологически посильным;
- шаг должен звучать как живое сообщение в мессенджере, а не как техзадание;
- не используй слова и обороты: "проход", "каркас", "зайдем руками", "войти руками", "буксуешь", "криво", "что-нибудь", "штуки", "погрузись", "исследуй", "настрой окружение", "сделай тестовый вариант", "подготовь материалы";
- давай один конкретный объект или одну конкретную задачу;
- если действие можно упростить бытовым способом, предложи запасной путь;
- после шага должно быть понятно, что человек присылает дальше.

Контекст бота:
- бот говорит коротко, живо, по-человечески;
- без пафоса, без коучинговой воды;
- не гадает пол пользователя;
- не звучит как школа или курс.

Выбранное направление:
{selected_direction}

Анкета пользователя:

1. Сколько у него свободного времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что он уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Что нужно выдать:
- ОДИН первый шаг;
- шаг должен быть либо:
  1) через один конкретный референс,
  2) через одно прямое бытовое действие,
  3) через сверхпошаговый вход для полного новичка;
- выбери тот формат, который лучше подходит именно этому направлению и этому человеку;
- не перегружай;
- без длинных списков равнозначных действий.

Про short_perspective:
- 1-2 коротких предложения о ближайшем результате без пафоса;
- без обещаний денег, клиентов и "успеха";
- без воды.

Верни ответ СТРОГО в JSON.

Формат:
{{
  "step_title": "Очень короткое название шага, 2-5 слов",
  "short_perspective": "1-2 коротких предложения про ближайший живой результат",
  "step_description": "Одной-двумя короткими фразами: что сейчас делаем и зачем",
  "why_this_step": "Почему начинаем именно так, по-человечески и конкретно",
  "how_to_do_it": [
    "Очень конкретный шаг 1 с буквальным объяснением",
    "Очень конкретный шаг 2",
    "Очень конкретный шаг 3",
    "Если нужен запасной путь — дай его тоже"
  ],
  "recommended_tools": [
    "Конкретный простой инструмент / место / сервис / материал"
  ],
  "success_criteria": "Что человек должен прислать или показать, чтобы было ясно, что шаг сделан"
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
ты не школьный проверяющий.
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
- если человек уловил суть и реально вошел в действие, лучше ставить done или partial, а не not_done;
- false negative хуже, чем чуть более добрый зачет;
- оценивай не "идеально ли по ТЗ", а "двигает ли это человека туда, куда нужен шаг";
- не фантазируй и не приписывай того, чего нет в расшифровке;
- если данных мало, выбирай partial или not_done;
- если человек сделал по-своему, но суть поймал, это чаще partial или done.

Как писать ответ:
- коротко, живо, по-человечески;
- без школьного тона;
- можно с мягким юмором;
- если работа мимо, сначала все равно признай сам факт действия, если он есть;
- если есть за что зацепиться, сначала назови конкретный удачный кусок;
- summary максимум 2-4 коротких предложения;
- strengths и what_to_fix — короткие и конкретные.

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
ты не школьный проверяющий.
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
- если на фото виден реальный результат и он близок к цели шага, лучше ставить done или partial, а не not_done;
- false negative хуже, чем чуть более добрый зачет;
- оценивай не "идеально ли соответствует", а "двигает ли это человека туда, куда нужен шаг";
- не фантазируй и не приписывай того, чего не видно;
- если по фото мало данных, чаще выбирай partial, а не резкий отказ;
- если человек сделал по-своему, но суть уловил, это чаще partial или done.

Как писать ответ:
- коротко, живо, по-человечески;
- без школьного тона;
- можно с мягким юмором;
- если работа мимо, сначала все равно признай сам факт действия, если он есть;
- если есть за что зацепиться, сначала назови конкретный удачный кусок;
- summary максимум 2-4 коротких предложения;
- strengths и what_to_fix — короткие и конкретные.

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
Ты строишь следующий шаг для пользователя Telegram-бота-наставника.

Критически важно:
- пользователь считается новичком, пока не доказано обратное;
- любой новый шаг должен быть объяснен простыми словами;
- если в шаге есть действие, ты сразу объясняешь, как его сделать буквально;
- не давай абстрактных формулировок;
- не используй слова и обороты: "проход", "каркас", "зайдем руками", "войти руками", "буксуешь", "криво", "что-нибудь", "штуки", "погрузись", "исследуй", "настрой окружение", "сделай тестовый вариант", "подготовь материалы";
- следующий шаг должен опираться на уже сделанное;
- усложнение должно быть аккуратным и только на одну ступень;
- не уводи человека в сторону.

Что нужно в следующем шаге:
- один конкретный следующий кусок;
- обычный человеческий язык;
- если можно упростить бытовым путем — предложи запасной вариант;
- после шага должно быть понятно, что человек присылает дальше;
- шаг должен выглядеть как сообщение в мессенджере, а не как учебная инструкция.

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

1. Сколько у него свободного времени / как он сейчас живет:
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
    "Очень конкретный шаг 1 с буквальным объяснением",
    "Очень конкретный шаг 2",
    "Очень конкретный шаг 3",
    "Если нужен запасной путь — дай его тоже"
  ],
  "recommended_tools": [
    "Конкретный простой инструмент / место / сервис / материал"
  ],
  "success_criteria": "Что человек должен прислать или показать, чтобы было ясно, что шаг сделан"
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
- без обещаний денег и успеха.

Верни ответ СТРОГО в JSON.

Формат:
{{
  "milestone_text": "1-2 коротких предложения"
}}
""".strip()

    def _build_direction_fit_prompt(
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
Ты объясняешь пользователю Telegram-бота, почему выбранное направление может ему подойти.

Критически важно:
- причина должна быть именно про человека;
- опирайся только на ответы анкеты;
- даже если связь косвенная, найди внятную человеческую причину;
- не используй аргументы про "легкий вход", "быстро", "удобно", "несложно", "хватит часа", "не займет много времени";
- не пиши воду;
- не делай психологический портрет;
- 2-3 коротких предложения максимум;
- говори живо и нормально.

Выбранное направление:
{selected_direction}

Анкета пользователя:

1. Сколько у него свободного времени / как он сейчас живет:
{current_income_source or "Не указано"}

2. К чему его тянет:
{free_time_style or "Не указано"}

3. Что он уже пробовал:
{appreciation_reason or "Не указано"}

4. На что в себе может опереться:
{help_request_reason or "Не указано"}

5. Свободный рассказ о себе:
{about_text or "Не указано"}

Верни ответ СТРОГО в JSON.

Формат:
{{
  "fit_reason": "Короткое человеческое объяснение, почему это направление может подойти именно этому человеку"
}}
""".strip()

    def _build_chat_reply_prompt(
        self,
        *,
        selected_direction: str | None,
        task_title: str | None,
        task_description: str | None,
        user_message: str,
        current_income_source: str | None,
        free_time_style: str | None,
        appreciation_reason: str | None,
        help_request_reason: str | None,
        about_text: str | None,
    ) -> str:
        task_block = task_title or "Активного шага сейчас нет"
        task_description_block = task_description or "Нет описания шага"

        return f"""
Ты отвечаешь пользователю Telegram-бота-наставника как живой человек в мессенджере.

Главные правила:
- ответ очень короткий: обычно 1-3 короткие фразы, максимум 4;
- без полотна;
- без списков, если можно без них;
- без канцелярита;
- без школьного тона;
- не используй слова и обороты: "проход", "каркас", "зайдем руками", "войти руками", "буксуешь", "криво";
- не гадай пол пользователя;
- не повторяй слово в слово формулировки из системных шаблонов;
- если ситуация нестандартная, сначала зацепись за конкретную фразу пользователя, потом мягко поведи дальше;
- если человек путается, отвечай проще;
- если человек тревожится, не дави;
- если человек шутит или ворчит, можно ответить по-человечески, но коротко;
- если у человека есть активный шаг, держи ответ рядом с ним;
- если активного шага нет, помогай двигаться дальше;
- не пиши длинных объяснений;
- не расписывай все сразу, оставляй только ближайший полезный ход;
- ориентир по длине: как обычное сообщение в чате, а не абзац из статьи;
- желательно уложиться примерно в 240 символов, если это возможно без потери смысла.

Контекст пользователя:
Направление: {selected_direction or "Не выбрано"}
Текущий шаг: {task_block}
Описание шага:
{task_description_block}

Анкета:
- Свободное время / как живет: {current_income_source or "Не указано"}
- К чему тянет: {free_time_style or "Не указано"}
- Что пробовал: {appreciation_reason or "Не указано"}
- На что может опереться: {help_request_reason or "Не указано"}
- Рассказ о себе: {about_text or "Не указано"}

Сообщение пользователя:
{user_message}

Верни ответ СТРОГО в JSON.

Формат:
{{
  "reply": "Очень короткий живой ответ в формате обычного сообщения в чате"
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
