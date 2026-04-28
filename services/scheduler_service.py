import asyncio
import logging
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

MSK_OFFSET_HOURS = 3
FOLLOWUP_SLOTS_MSK = (11, 21)

RECENT_USER_ACTIVITY_HOURS = 2
PUSH_MIN_SILENCE_HOURS = 18
PUSH_COOLDOWN_HOURS = 48
MILESTONE_INTERVAL_DAYS = 3

FOLLOWUP_QUESTION_DELAY_SECONDS = 60
FOLLOWUP_SOFT_ENTRY_DELAY_SECONDS = 15 * 60


def _utcnow() -> datetime:
    return datetime.utcnow()


def _to_msk(utc_dt: datetime) -> datetime:
    return utc_dt + timedelta(hours=MSK_OFFSET_HOURS)


def _from_msk(msk_dt: datetime) -> datetime:
    return msk_dt - timedelta(hours=MSK_OFFSET_HOURS)


def _next_followup_time() -> datetime:
    now_utc = _utcnow()
    now_msk = _to_msk(now_utc)

    for hour in FOLLOWUP_SLOTS_MSK:
        candidate_msk = now_msk.replace(
            hour=hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if candidate_msk > now_msk:
            return _from_msk(candidate_msk)

    next_day_first_slot = (now_msk + timedelta(days=1)).replace(
        hour=FOLLOWUP_SLOTS_MSK[0],
        minute=0,
        second=0,
        microsecond=0,
    )
    return _from_msk(next_day_first_slot)


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

    questions = [
        "Ты где пропала?",
        "Ты как там?",
        "Ты на связи?",
        "Как у тебя с движением?",
        "Ты где потерялась?",
    ]

    soft_entries = [
        "Давай спокойно: просто вернись на 10 минут.",
        "Можно без подвига. Один маленький заход — уже хорошо.",
        "Не надо идеально. Нужен просто живой вход обратно.",
        "Зайди коротко. Хоть с одного маленького куска.",
        "Просто вернись в процесс. Без лишнего давления.",
    ]

    question = questions[0]
    soft_entry = soft_entries[0]

    if name:
        question = f"{name}, {question[0].lower() + question[1:]}"

    return question, soft_entry, "regular_no_task"


def _build_burnout_followup(user: User, profile: UserProfile | None) -> tuple[str, str, str]:
    name = _get_user_name(user)
    _energy_level = (profile.energy_level or "").strip().lower() if profile else ""

    questions = [
        "Ты как сейчас?",
        "Как ты?",
        "Ты в порядке?",
        "Как ты сегодня?",
    ]

    soft_entries = [
        "Без рывка. Просто можно вернуться совсем маленьким шагом.",
        "Сейчас не нужен подвиг. Нужен тихий, живой вход обратно.",
        "Если тяжело — не тащи всё. Возьми самый маленький кусок.",
        "Можно мягко. Главное — не исчезать из процесса совсем.",
    ]

    question = questions[0]
    soft_entry = soft_entries[0]

    if name:
        question = f"{name}, {question[0].lower() + question[1:]}"

    return question, soft_entry, "burnout_no_task"


def _build_push_followup(user: User) -> tuple[str, str, str]:
    name = _get_user_name(user)

    questions = [
        "Ты где пропала?",
        "Ты куда выпала?",
        "Ты ещё здесь?",
        "Как ты там?",
    ]

    soft_entries = [
        "Давай просто вернёмся в движение. Хоть на 10 минут.",
        "Не нужен идеал. Нужен один реальный кусок сегодня.",
        "Можно коротко. Главное — снова зайти в процесс.",
        "Хватит одного маленького шага, чтобы снова поймать темп.",
    ]

    question = questions[0]
    soft_entry = soft_entries[0]

    if name:
        question = f"{name}, {question[0].lower() + question[1:]}"

    return question, soft_entry, "push_no_task"


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

    return True


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


async def _user_replied_after(user_id: int, started_at: datetime) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User.last_user_message_at).where(User.id == user_id)
        )
        last_user_message_at = result.scalar_one_or_none()

    if last_user_message_at is None:
        return False

    return last_user_message_at > started_at


async def _send_staged_followup_sequence(
    bot: Bot,
    user: User,
    sticker_pack: str,
    question_text: str,
    soft_entry_text: str,
    started_at: datetime,
) -> None:
    await _send_required_sticker(bot, user.telegram_user_id, sticker_pack)

    await asyncio.sleep(FOLLOWUP_QUESTION_DELAY_SECONDS)
    if await _user_replied_after(user.id, started_at):
        logger.info("followup_sequence_stopped_after_sticker user_id=%s", user.id)
        return

    await bot.send_message(user.telegram_user_id, question_text)

    await asyncio.sleep(FOLLOWUP_SOFT_ENTRY_DELAY_SECONDS)
    if await _user_replied_after(user.id, started_at):
        logger.info("followup_sequence_stopped_after_question user_id=%s", user.id)
        return

    await bot.send_message(user.telegram_user_id, soft_entry_text)
    logger.info("followup_sequence_completed user_id=%s", user.id)


async def _send_followup(
    bot: Bot,
    user: User,
    profile: UserProfile | None,
    now: datetime,
) -> tuple[str, bool]:
    if _is_burnout_state(profile):
        question_text, soft_entry_text, followup_type = _build_burnout_followup(user, profile)
        asyncio.create_task(
            _send_staged_followup_sequence(
                bot=bot,
                user=user,
                sticker_pack="followup_live",
                question_text=question_text,
                soft_entry_text=soft_entry_text,
                started_at=now,
            )
        )
        return followup_type, False

    if _should_send_push_followup(user, profile, now):
        question_text, soft_entry_text, followup_type = _build_push_followup(user)
        asyncio.create_task(
            _send_staged_followup_sequence(
                bot=bot,
                user=user,
                sticker_pack="push_soft",
                question_text=question_text,
                soft_entry_text=soft_entry_text,
                started_at=now,
            )
        )
        return followup_type, True

    question_text, soft_entry_text, followup_type = _build_regular_followup(user)
    asyncio.create_task(
        _send_staged_followup_sequence(
            bot=bot,
            user=user,
            sticker_pack="followup_live",
            question_text=question_text,
            soft_entry_text=soft_entry_text,
            started_at=now,
        )
    )
    return followup_type, False


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

            if user.push_explanation_due_at is not None and user.push_explanation_due_at <= now:
                user.push_explanation_due_at = None

            if user.last_user_message_at and user.last_user_message_at > now - timedelta(hours=RECENT_USER_ACTIVITY_HOURS):
                user.next_followup_at = _next_followup_time()
                user.push_explanation_due_at = None
                user.updated_at = now
                continue

            try:
                milestone_sent = await _send_milestone_if_due(
                    bot,
                    user,
                    profile,
                    now,
                )

                if milestone_sent:
                    user.next_followup_at = _next_followup_time()
                    user.push_explanation_due_at = None
                    user.updated_at = now
                    continue

                if user.next_followup_at is not None and user.next_followup_at > now:
                    user.updated_at = now
                    continue

                followup_type, is_push = await _send_followup(
                    bot,
                    user,
                    profile,
                    now,
                )

                user.last_followup_sent_at = now
                user.last_followup_type = followup_type
                user.next_followup_at = _next_followup_time()
                user.updated_at = now

                if is_push:
                    user.last_push_followup_at = now

                user.push_explanation_due_at = None

            except Exception:
                logger.exception("Ошибка при отправке follow-up пользователю id=%s", user.id)
                user.next_followup_at = _next_followup_time()
                user.push_explanation_due_at = None
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
