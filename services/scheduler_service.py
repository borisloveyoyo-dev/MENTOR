import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from bot.stickers import get_random_sticker_file_id
from db.database import async_session_maker
from db.models import User, UserProfile, UserTask
from services.milestone_service import (
    MilestoneServiceError,
    build_user_milestone_text,
)

logger = logging.getLogger(__name__)

SCHEDULER_POLL_SECONDS = 300
FOLLOWUP_MIN_HOURS = 6
FOLLOWUP_MAX_HOURS = 12

RECENT_USER_ACTIVITY_HOURS = 2
PUSH_MIN_SILENCE_HOURS = 18
PUSH_COOLDOWN_HOURS = 48
PUSH_EXPLANATION_DELAY_HOURS = 12
MILESTONE_INTERVAL_DAYS = 3


def _utcnow() -> datetime:
    return datetime.utcnow()


def _random_next_followup_time() -> datetime:
    hours = random.randint(FOLLOWUP_MIN_HOURS, FOLLOWUP_MAX_HOURS)
    minutes = random.randint(0, 59)
    return _utcnow() + timedelta(hours=hours, minutes=minutes)


def _random_push_explanation_time() -> datetime:
    minutes = random.randint(0, 45)
    return _utcnow() + timedelta(hours=PUSH_EXPLANATION_DELAY_HOURS, minutes=minutes)


def _has_pending_task(user: User) -> bool:
    return any(task.status == "pending" for task in user.tasks)


def _get_latest_pending_task(user: User) -> UserTask | None:
    pending_tasks = [task for task in user.tasks if task.status == "pending"]
    if not pending_tasks:
        return None

    pending_tasks.sort(
        key=lambda task: task.assigned_at or datetime.min,
        reverse=True,
    )
    return pending_tasks[0]


def _is_burnout_state(profile: UserProfile | None) -> bool:
    if profile is None:
        return False

    energy_level = (profile.energy_level or "").strip().lower()
    if profile.burnout_flag:
        return True

    return energy_level in {"low", "very_low", "empty", "burnout"}


def _get_user_name(user: User) -> str:
    return (user.first_name or "").strip()


def _should_send_milestone(user: User, profile: UserProfile | None, now: datetime) -> bool:
    if not user.selected_direction:
        return False

    if profile is None:
        return False

    if profile.onboarding_completed_at is None:
        return False

    if profile.onboarding_completed_at > now - timedelta(days=MILESTONE_INTERVAL_DAYS):
        return False

    if user.last_milestone_sent_at is not None:
        if user.last_milestone_sent_at > now - timedelta(days=MILESTONE_INTERVAL_DAYS):
            return False

    return True


def _build_regular_followup(user: User) -> tuple[str, str, str]:
    name = _get_user_name(user)

    openers = [
        "Ты где завис?",
        "Ты где?",
        "Почему завис?",
        "Ты чего пропал?",
        "Ну ты где там?",
        "Куда выпал?",
    ]

    second_touches = [
        "Сделай лучше криво, чем никак.",
        "Не шлифуй. Просто зайди обратно.",
        "Один маленький кусок — уже нормально.",
        "Не думай слишком долго. Зайди руками.",
        "Хотя бы короткий заход сегодня.",
    ]

    opener = random.choice(openers)
    second_touch = random.choice(second_touches)

    if name and random.random() < 0.45:
        opener = f"{name}, {opener[0].lower() + opener[1:]}"

    return opener, second_touch, "regular_no_task"


def _build_burnout_followup(user: User, profile: UserProfile | None) -> tuple[str, str, str]:
    name = _get_user_name(user)
    _energy_level = (profile.energy_level or "").strip().lower() if profile else ""

    openers = [
        "Как ты?",
        "Ты как сейчас?",
        "Я не давлю. Просто скажи, как ты.",
        "Давай без рывков. Как ты сейчас?",
    ]

    support_lines = [
        "Ты устал не от задачи, а от того, что она висит в голове и давит.",
        "Сейчас не нужен рывок. Нужен маленький живой вход обратно.",
        "Если тяжело, не тащи все целиком. Зацепись за самый край.",
        "Сейчас важнее выдохнуть и вернуться маленьким шагом.",
    ]

    opener = random.choice(openers)
    support = random.choice(support_lines)

    if name and random.random() < 0.45:
        opener = f"{name}, {opener[0].lower() + opener[1:]}"

    return opener, support, "burnout_no_task"


def _build_push_followup(user: User) -> tuple[str, str, str]:
    name = _get_user_name(user)

    openers = [
        "Ты чего завис?",
        "Так, ты где?",
        "Не пропадай.",
        "Ну-ка вернись в движение.",
    ]

    second_touches = [
        "Нужен не рывок. Нужен короткий заход.",
        "Хотя бы 10 минут чего-то реального сегодня.",
        "Один маленький кусок сегодня — и уже хорошо.",
        "Сейчас не идеал нужен. Нужен вход обратно.",
    ]

    opener = random.choice(openers)
    second_touch = random.choice(second_touches)

    if name and random.random() < 0.45:
        opener = f"{name}, {opener[0].lower() + opener[1:]}"

    return opener, second_touch, "push_no_task"


def _build_push_explanation_followup(user: User) -> tuple[str, str]:
    name = _get_user_name(user)

    openers = [
        "Я тогда написал жестче не чтобы додавить тебя.",
        "Прошлое сообщение было резче специально.",
        "Я не хотел давить. Я хотел вытащить тебя из зависания.",
    ]

    opener = random.choice(openers)
    if name and random.random() < 0.35:
        opener = f"{name}, {opener[0].lower() + opener[1:]}"

    text = (
        f"{opener}\n\n"
        "Тут не нужен идеальный результат. Нужен маленький реальный шаг."
    )
    return text, "push_explanation_no_task"


def _should_send_push_followup(user: User, profile: UserProfile | None, now: datetime) -> bool:
    if _is_burnout_state(profile):
        return False

    if not _has_pending_task(user):
        return False

    if user.last_user_message_at is None:
        return False

    if user.last_user_message_at > now - timedelta(hours=PUSH_MIN_SILENCE_HOURS):
        return False

    if user.last_push_followup_at is not None:
        if user.last_push_followup_at > now - timedelta(hours=PUSH_COOLDOWN_HOURS):
            return False

    if user.last_followup_type and user.last_followup_type.startswith("push_explanation"):
        return False

    return random.random() < 0.25


async def _send_required_sticker(bot: Bot, telegram_user_id: int, pack_name: str) -> None:
    sticker_id = get_random_sticker_file_id(pack_name)
    if not sticker_id:
        logger.warning(
            "required_sticker_missing pack=%s telegram_user_id=%s",
            pack_name,
            telegram_user_id,
        )
        return

    try:
        await bot.send_sticker(telegram_user_id, sticker_id)
        logger.info(
            "required_sticker_sent pack=%s telegram_user_id=%s",
            pack_name,
            telegram_user_id,
        )
    except Exception:
        logger.exception(
            "required_sticker_failed pack=%s telegram_user_id=%s",
            pack_name,
            telegram_user_id,
        )


async def _send_two_touch_followup(
    bot: Bot,
    telegram_user_id: int,
    first_text: str,
    second_text: str,
) -> None:
    await bot.send_message(telegram_user_id, first_text)
    await asyncio.sleep(random.randint(2, 5))
    await bot.send_message(telegram_user_id, second_text)


async def _send_followup(
    bot: Bot,
    user: User,
    profile: UserProfile | None,
    now: datetime,
) -> tuple[str, bool, bool]:
    if user.push_explanation_due_at is not None and user.push_explanation_due_at <= now:
        text, followup_type = _build_push_explanation_followup(user)
        await bot.send_message(user.telegram_user_id, text)
        return followup_type, False, True

    if _is_burnout_state(profile):
        await _send_required_sticker(bot, user.telegram_user_id, "followup_live")
        first_text, second_text, followup_type = _build_burnout_followup(user, profile)
        await _send_two_touch_followup(
            bot,
            user.telegram_user_id,
            first_text,
            second_text,
        )
        return followup_type, False, False

    if _should_send_push_followup(user, profile, now):
        await _send_required_sticker(bot, user.telegram_user_id, "push_soft")
        first_text, second_text, followup_type = _build_push_followup(user)
        await _send_two_touch_followup(
            bot,
            user.telegram_user_id,
            first_text,
            second_text,
        )
        return followup_type, True, False

    await _send_required_sticker(bot, user.telegram_user_id, "followup_live")
    first_text, second_text, followup_type = _build_regular_followup(user)
    await _send_two_touch_followup(
        bot,
        user.telegram_user_id,
        first_text,
        second_text,
    )
    return followup_type, False, False


async def _send_milestone_if_due(
    bot: Bot,
    user: User,
    profile: UserProfile | None,
    now: datetime,
) -> bool:
    if not _should_send_milestone(user, profile, now):
        return False

    try:
        milestone_text = await build_user_milestone_text(
            user_id=user.id,
            selected_direction=user.selected_direction or "",
        )
    except MilestoneServiceError:
        logger.exception("Не удалось собрать маяк для user id=%s", user.id)
        return False
    except Exception:
        logger.exception("Неожиданная ошибка при сборке маяка для user id=%s", user.id)
        return False

    if not milestone_text:
        return False

    try:
        await bot.send_message(
            user.telegram_user_id,
            f"Смотри, наш ближайший маяк:\n\n{milestone_text}",
        )
    except Exception:
        logger.exception("Не удалось отправить маяк пользователю id=%s", user.id)
        return False

    user.last_milestone_sent_at = now
    user.updated_at = now
    return True


async def _process_due_users(bot: Bot) -> None:
    now = _utcnow()

    async with async_session_maker() as session:
        result = await session.execute(
            select(User)
            .options(
                selectinload(User.profile),
                selectinload(User.tasks),
            )
            .where(User.is_onboarding_completed.is_(True))
            .where(User.selected_direction.is_not(None))
            .where(
                or_(
                    User.next_followup_at.is_(None),
                    User.next_followup_at <= now,
                    User.push_explanation_due_at <= now,
                )
            )
        )
        users = result.scalars().all()

        if not users:
            return

        for user in users:
            profile = user.profile

            if user.last_user_message_at and user.last_user_message_at > now - timedelta(hours=RECENT_USER_ACTIVITY_HOURS):
                user.next_followup_at = _random_next_followup_time()
                user.push_explanation_due_at = None
                continue

            try:
                milestone_sent = await _send_milestone_if_due(
                    bot,
                    user,
                    profile,
                    now,
                )

                if milestone_sent:
                    user.next_followup_at = _random_next_followup_time()
                    user.push_explanation_due_at = None
                    user.updated_at = now
                    continue

                followup_type, is_push, is_explanation = await _send_followup(
                    bot,
                    user,
                    profile,
                    now,
                )

                user.last_followup_sent_at = now
                user.last_followup_type = followup_type
                user.next_followup_at = _random_next_followup_time()
                user.updated_at = now

                if is_push:
                    user.last_push_followup_at = now
                    user.push_explanation_due_at = _random_push_explanation_time()
                elif is_explanation:
                    user.push_explanation_due_at = None
                else:
                    user.push_explanation_due_at = None

            except Exception:
                logger.exception("Ошибка при отправке follow-up пользователю id=%s", user.id)
                user.next_followup_at = _random_next_followup_time()
                user.updated_at = now

        await session.commit()


class SchedulerService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._is_running = False

    async def start(self) -> None:
        if self._is_running:
            return

        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._is_running = False

        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        while self._is_running:
            try:
                await _process_due_users(self.bot)
            except Exception:
                logger.exception("Ошибка в scheduler loop")

            await asyncio.sleep(SCHEDULER_POLL_SECONDS)
