import json
from datetime import datetime

from sqlalchemy import func, select

from db.database import async_session_maker
from db.models import User, UserProfile, UserTask
from services.ai_service import AIService


class MentorServiceError(Exception):
    pass


DIFFICULTY_LADDER = ("starter", "base", "growth", "pro")
DEFAULT_DIFFICULTY_MODE = "starter"


class MentorService:
    def __init__(self) -> None:
        self.ai_service = AIService()

    async def analyze_profile_and_save_result(self, user_id: int) -> tuple[str, list[dict[str, str]]]:
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if profile is None:
                raise MentorServiceError("Профиль пользователя не найден")

            if not self._has_enough_data(profile):
                raise MentorServiceError("Для анализа пока недостаточно данных профиля")

            analysis = await self.ai_service.analyze_user_profile(
                current_income_source=profile.current_income_source,
                free_time_style=profile.free_time_style,
                appreciation_reason=profile.appreciation_reason,
                help_request_reason=profile.help_request_reason,
                about_text=profile.about_text,
            )

            directions = analysis.directions[:5]
            directions_payload = [
                {
                    "title": item.title,
                    "description": item.description,
                }
                for item in directions
            ]

            formatted_text = self._build_user_message(
                summary=analysis.summary,
                directions=directions_payload,
            )

            profile.profile_summary = formatted_text
            profile.generated_directions_json = json.dumps(directions_payload, ensure_ascii=False)
            profile.updated_at = datetime.utcnow()

            await session.commit()

            return formatted_text, directions_payload

    async def get_saved_directions(self, user_id: int) -> list[dict[str, str]]:
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if profile is None or not profile.generated_directions_json:
                return []

            try:
                data = json.loads(profile.generated_directions_json)
            except json.JSONDecodeError:
                return []

            if not isinstance(data, list):
                return []

            directions: list[dict[str, str]] = []

            for item in data:
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

                directions.append(
                    {
                        "title": title,
                        "description": description,
                    }
                )

            return directions[:5]

    async def save_selected_direction(self, user_id: int, direction_title: str) -> None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                raise MentorServiceError("Пользователь не найден")

            user.selected_direction = direction_title
            user.updated_at = datetime.utcnow()

            await session.commit()

    async def generate_first_task_after_direction_choice(self, user_id: int) -> dict:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                raise MentorServiceError("Пользователь не найден")

            if not user.selected_direction:
                raise MentorServiceError("У пользователя пока не выбрано направление")

            profile_result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = profile_result.scalar_one_or_none()

            if profile is None:
                raise MentorServiceError("Профиль пользователя не найден")

            selected_direction_context = self._build_selected_direction_context(
                selected_direction_title=user.selected_direction,
                generated_directions_json=profile.generated_directions_json,
            )

            plan = await self.ai_service.generate_first_step_plan(
                selected_direction=selected_direction_context,
                current_income_source=profile.current_income_source,
                free_time_style=profile.free_time_style,
                appreciation_reason=profile.appreciation_reason,
                help_request_reason=profile.help_request_reason,
                about_text=profile.about_text,
            )

            task_description = self._build_task_description(
                step_description=plan.step_description,
                why_this_step=plan.why_this_step,
                how_to_do_it=plan.how_to_do_it,
                recommended_tools=plan.recommended_tools,
                success_criteria=plan.success_criteria,
            )

            difficulty_mode = self.get_first_task_difficulty_mode()

            task = UserTask(
                user_id=user_id,
                title=plan.step_title,
                description=task_description,
                status="pending",
                difficulty_mode=difficulty_mode,
            )
            session.add(task)

            await session.commit()

            return {
                "task_title": plan.step_title,
                "short_perspective": plan.short_perspective,
                "step_description": plan.step_description,
                "why_this_step": plan.why_this_step,
                "how_to_do_it": plan.how_to_do_it,
                "recommended_tools": plan.recommended_tools,
                "success_criteria": plan.success_criteria,
                "difficulty_mode": difficulty_mode,
            }

    async def get_latest_pending_task_title(self, user_id: int) -> str | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(UserTask)
                .where(UserTask.user_id == user_id)
                .where(UserTask.status == "pending")
                .order_by(UserTask.assigned_at.desc())
            )
            task = result.scalars().first()

            if task is None or not task.title:
                return None

            return task.title.strip()

    async def get_completed_tasks_count(self, user_id: int) -> int:
        async with async_session_maker() as session:
            result = await session.execute(
                select(func.count(UserTask.id))
                .where(UserTask.user_id == user_id)
                .where(UserTask.status == "done")
            )
            count = result.scalar_one()
            return int(count or 0)

    def get_first_task_difficulty_mode(self) -> str:
        return DEFAULT_DIFFICULTY_MODE

    def normalize_difficulty_mode(self, difficulty_mode: str | None) -> str:
        normalized = (difficulty_mode or "").strip().lower()
        if normalized in DIFFICULTY_LADDER:
            return normalized
        return DEFAULT_DIFFICULTY_MODE

    def infer_difficulty_mode_from_progress(self, completed_tasks_count: int) -> str:
        if completed_tasks_count <= 0:
            return "starter"
        if completed_tasks_count <= 2:
            return "base"
        if completed_tasks_count <= 5:
            return "growth"
        return "pro"

    def build_next_difficulty_mode(
        self,
        *,
        current_difficulty_mode: str | None,
        completed_tasks_count: int,
        next_step_mode: str,
    ) -> str:
        normalized_next_step_mode = (next_step_mode or "").strip().lower()
        fallback_mode = self.infer_difficulty_mode_from_progress(completed_tasks_count)

        current_mode = self.normalize_difficulty_mode(current_difficulty_mode)
        if current_mode not in DIFFICULTY_LADDER:
            current_mode = fallback_mode

        current_index = DIFFICULTY_LADDER.index(current_mode)

        if normalized_next_step_mode == "easier":
            return DIFFICULTY_LADDER[max(0, current_index - 1)]

        if normalized_next_step_mode == "same":
            return DIFFICULTY_LADDER[current_index]

        if normalized_next_step_mode == "harder":
            target_index = min(len(DIFFICULTY_LADDER) - 1, current_index + 1)
            return DIFFICULTY_LADDER[target_index]

        return current_mode

    def detect_user_state_from_text(self, text: str) -> dict | None:
        normalized = self._normalize_text(text)

        if not normalized:
            return None

        burnout_keywords = [
            "выгор",
            "выгорел",
            "выгорела",
            "не вывожу",
            "не вывозю",
            "не тяну",
            "сил нет",
            "без сил",
            "не могу собраться",
            "не хочу ничего",
            "ничего не хочу",
            "разбит",
            "разбита",
            "пусто внутри",
            "устал",
            "устала",
            "сдулся",
            "сдулась",
        ]

        stuck_keywords = [
            "не сделал",
            "не сделала",
            "не могу начать",
            "не получается начать",
            "застрял",
            "застряла",
            "завис",
            "зависла",
            "откладываю",
            "прокрастинирую",
            "буксую",
            "не двигается",
            "выпал",
            "выпала",
        ]

        recovery_keywords = [
            "отпустило",
            "полегче",
            "стало лучше",
            "собрался",
            "собралась",
            "вернулся",
            "вернулась",
            "готов дальше",
            "готова дальше",
            "могу продолжать",
        ]

        progress_keywords = [
            "сделал",
            "сделала",
            "начал",
            "начала",
            "продвинулся",
            "продвинулась",
            "получилось",
            "готово",
            "закончил",
            "закончила",
        ]

        if self._contains_any(normalized, burnout_keywords):
            return {
                "state_code": "burnout",
                "energy_level": "burnout",
                "burnout_flag": True,
            }

        if self._contains_any(normalized, stuck_keywords):
            return {
                "state_code": "stuck",
                "energy_level": "low",
                "burnout_flag": False,
            }

        if self._contains_any(normalized, recovery_keywords):
            return {
                "state_code": "recovery",
                "energy_level": "normal",
                "burnout_flag": False,
            }

        if self._contains_any(normalized, progress_keywords):
            return {
                "state_code": "progress",
                "energy_level": "normal",
                "burnout_flag": False,
            }

        return None

    def build_state_reply(self, state_code: str, task_title: str | None) -> str:
        task_block = ""
        if task_title:
            task_block = f"Текущий шаг:\n— {task_title}\n\n"

        if state_code == "burnout":
            return (
                "Понял. Тогда не давим.\n\n"
                "Сейчас задача не в том, чтобы выжать из себя максимум, а в том, чтобы не потерять контакт с движением.\n\n"
                f"{task_block}"
                "Сделай только самый маленький кусок на 5–10 минут. Этого достаточно для возвращения."
            )

        if state_code == "stuck":
            return (
                "Окей. Значит проблема не в тебе, а в заходе в задачу.\n\n"
                f"{task_block}"
                "Не тащи все сразу. Открой задачу, выбери самый легкий кусок и добей только его."
            )

        if state_code == "recovery":
            return (
                "Хорошо. Значит можно спокойно возвращаться в ритм.\n\n"
                f"{task_block}"
                "Не пытайся резко ускориться. Возьми один конкретный кусок и сделай его нормально."
            )

        if state_code == "progress":
            return (
                "Вот, уже лучше.\n\n"
                "Это и есть движение.\n\n"
                f"{task_block}"
                "Теперь не расплескай темп: следующий шаг тоже держи маленьким и конкретным."
            )

        return (
            "Принял.\n\n"
            f"{task_block}"
            "Давай держаться за конкретное действие, а не за внутреннюю суету."
        )

    def _has_enough_data(self, profile: UserProfile) -> bool:
        values = [
            profile.current_income_source,
            profile.free_time_style,
            profile.appreciation_reason,
            profile.help_request_reason,
            profile.about_text,
        ]
        filled_count = sum(1 for value in values if value and value.strip())
        return filled_count >= 4

    def _build_user_message(
        self,
        *,
        summary: str,
        directions: list[dict[str, str]],
    ) -> str:
        lines: list[str] = []

        lines.append("Слушай, я посмотрел на то, что ты рассказал.")
        lines.append("")
        lines.append(summary)
        lines.append("")
        lines.append("Вот несколько живых вариантов, куда можно попробовать двинуться:")
        lines.append("")

        for index, direction in enumerate(directions, start=1):
            lines.append(f"{index}. {direction['title']}")
            lines.append(direction["description"])
            lines.append("")

        lines.append("Не как приговор, а как хорошие точки входа. Посмотри, что тебе отзывается сильнее.")

        return "\n".join(lines).strip()

    def _build_selected_direction_context(
        self,
        *,
        selected_direction_title: str,
        generated_directions_json: str | None,
    ) -> str:
        if not generated_directions_json:
            return selected_direction_title

        try:
            data = json.loads(generated_directions_json)
        except json.JSONDecodeError:
            return selected_direction_title

        if not isinstance(data, list):
            return selected_direction_title

        for item in data:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            description = item.get("description")

            if not isinstance(title, str) or not isinstance(description, str):
                continue

            if title.strip() == selected_direction_title.strip():
                return f"{title.strip()}: {description.strip()}"

        return selected_direction_title

    def _build_task_description(
        self,
        *,
        step_description: str,
        why_this_step: str,
        how_to_do_it: list[str],
        recommended_tools: list[str],
        success_criteria: str,
    ) -> str:
        lines: list[str] = []

        lines.append(step_description)
        lines.append("")
        lines.append(f"Почему сейчас лучше начать с этого: {why_this_step}")
        lines.append("")
        lines.append("Как сделать:")

        for item in how_to_do_it:
            lines.append(f"- {item}")

        if recommended_tools:
            lines.append("")
            lines.append("Что может помочь:")
            for item in recommended_tools:
                lines.append(f"- {item}")

        lines.append("")
        lines.append(f"Как понять, что шаг сделан: {success_criteria}")

        return "\n".join(lines)

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.lower().strip().split())

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)


async def analyze_user_profile_and_save(user_id: int) -> tuple[str, list[dict[str, str]]]:
    service = MentorService()
    return await service.analyze_profile_and_save_result(user_id)


async def get_saved_profile_directions(user_id: int) -> list[dict[str, str]]:
    service = MentorService()
    return await service.get_saved_directions(user_id)


async def save_user_selected_direction(user_id: int, direction_title: str) -> None:
    service = MentorService()
    await service.save_selected_direction(user_id, direction_title)


async def generate_first_task_for_user(user_id: int) -> dict:
    service = MentorService()
    return await service.generate_first_task_after_direction_choice(user_id)


async def get_latest_pending_task_title(user_id: int) -> str | None:
    service = MentorService()
    return await service.get_latest_pending_task_title(user_id)


async def get_completed_tasks_count_for_user(user_id: int) -> int:
    service = MentorService()
    return await service.get_completed_tasks_count(user_id)


def get_first_task_difficulty_mode() -> str:
    service = MentorService()
    return service.get_first_task_difficulty_mode()


def normalize_task_difficulty_mode(difficulty_mode: str | None) -> str:
    service = MentorService()
    return service.normalize_difficulty_mode(difficulty_mode)


def infer_task_difficulty_mode_from_progress(completed_tasks_count: int) -> str:
    service = MentorService()
    return service.infer_difficulty_mode_from_progress(completed_tasks_count)


def build_next_task_difficulty_mode(
    *,
    current_difficulty_mode: str | None,
    completed_tasks_count: int,
    next_step_mode: str,
) -> str:
    service = MentorService()
    return service.build_next_difficulty_mode(
        current_difficulty_mode=current_difficulty_mode,
        completed_tasks_count=completed_tasks_count,
        next_step_mode=next_step_mode,
    )


def detect_user_state_from_text(text: str) -> dict | None:
    service = MentorService()
    return service.detect_user_state_from_text(text)


def build_state_reply(state_code: str, task_title: str | None) -> str:
    service = MentorService()
    return service.build_state_reply(state_code, task_title)
