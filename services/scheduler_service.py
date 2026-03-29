import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from db.database import async_session_maker
from db.models import User, UserProfile, UserTask

logger = logging.getLogger(__name__)

SCHEDULER_POLL_SECONDS = 300
FOLLOWUP_MIN_HOURS = 6
FOLLOWUP_MAX_HOURS = 12

RECENT_USER_ACTIVITY_HOURS = 2
PUSH_MIN_SILENCE_HOURS = 18
PUSH_COOLDOWN_HOURS = 48
PUSH_EXPLANATION_DELAY_HOURS = 12


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


def _build_regular_followup(user: User) -> tuple[str, str]:
    openers = [
        "Ты где завис?",
        "Ты чего затих?",
        "Ну и что случилось?",
        "Я тебя потерял. Что там у тебя?",
        "Слушай, что тебя сейчас стопорит?",
        "Ты где сейчас — в деле, в сомнениях или просто устал?",
    ]

    insights = [
        "Сначала соберем, потом улучшим.",
        "Криво — нормально. Пусто — хуже.",
        "Не шлифуй то, чего еще нет.",
        "Большое не упрощаем. Большое разбираем.",
        "Обычно самый вязкий этап — после первого старта.",
        "Чаще всего стопор не в лени, а в перегруженном входе.",
    ]

    opener = random.choice(openers)
    insight = random.choice(insights)

    text = (
        f"{opener}\n\n"
        f"{insight}"
    )
    return text, "regular_no_task"


def _build_burnout_followup(user: User, profile: UserProfile | None) -> tuple[str, str]:
    energy_level = (profile.energy_level or "").strip().lower() if profile else ""

    openers = [
        "Ну как ты себя чувствуешь?",
        "Давай просто поболтаем. Как ты?",
        "Я не давлю. Просто хочу понять, как ты сейчас.",
        "Сейчас не тащу тебя в задачу. Просто скажи, как ты.",
    ]

    support_lines = [
        "Ты устал не от задачи, а от того, что она висит в голове и давит.",
        "Сейчас важнее выдохнуть, чем героически тащить все сразу.",
        "Иногда лучший ход — не рывок, а очень маленький вход обратно.",
        "Если сил мало, не надо тащить весь кусок. Достаточно зацепиться за край.",
    ]

    opener = random.choice(openers)
    support = random.choice(support_lines)

    if energy_level in {"low", "very_low", "empty", "burnout"}:
        text = (
            f"{opener}\n\n"
            f"{support}"
        )
        return text, "burnout_no_task"

    text = (
        f"{opener}\n\n"
        f"{support}"
    )
    return text, "burnout_no_task"


def _build_push_followup(user: User) -> tuple[str, str]:
    push_messages = [
        (
            "Так, стоп.\n\n"
            "Ты сейчас больше крутишь это в голове, чем двигаешь.\n\n"
            "Нужен один короткий честный заход сегодня."
        ),
        (
            "Хватит ждать нужного состояния.\n\n"
            "Нужен не рывок. Нужен короткий вход."
        ),
        (
            "Не пропадай.\n\n"
            "Один маленький кусок сегодня — и уже нормально."
        ),
        (
            "Пора возвращаться в движение.\n\n"
            "Хотя бы 10 минут чего-то реального сегодня."
        ),
    ]

    return random.choice(push_messages), "push_no_task"


def _build_push_explanation_followup(user: User) -> tuple[str, str]:
    openers = [
        "Я тогда написал жестче не чтобы додавить тебя.",
        "Прошлое сообщение было резче специально.",
        "Я не хотел давить. Я хотел вытащить тебя из зависания.",
    ]

    opener = random.choice(openers)

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
        text, followup_type = _build_burnout_followup(user, profile)
        await bot.send_message(user.telegram_user_id, text)
        return followup_type, False, False

    if _should_send_push_followup(user, profile, now):
        text, followup_type = _build_push_followup(user)
        await bot.send_message(user.telegram_user_id, text)
        return followup_type, True, False

    text, followup_type = _build_regular_followup(user)
    await bot.send_message(user.telegram_user_id, text)
    return followup_type, False, False


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
                followup_type, is_push, is_explanation = await _send_followup(
                    bot,
                    user,
                    profile,
                    now,
                )

                user.last_followup_sent_at = now
                user.last_followup_type = followup_type
                user.updated_at = now

                if is_push:
                    user.last_push_followup_at = now
                    user.push_explanation_due_at = _random_push_explanation_time()
                    user.next_followup_at = _random_next_followup_time()
                elif is_explanation:
                    user.push_explanation_due_at = None
                    user.next_followup_at = _random_next_followup_time()
                else:
                    user.next_followup_at = _random_next_followup_time()

            except Exception as e:
                logger.exception(
                    "Failed to send follow-up to telegram_user_id=%s: %s",
                    user.telegram_user_id,
                    e,
                )

        await session.commit()


async def scheduler_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    logger.info("Scheduler loop started")

    while not stop_event.is_set():
        try:
            await _process_due_users(bot)
        except Exception as e:
            logger.exception("Scheduler iteration failed: %s", e)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SCHEDULER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass

    logger.info("Scheduler loop stopped")


class SchedulerService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            scheduler_loop(self.bot, self._stop_event)
        )

    async def stop(self) -> None:
        self._stop_event.set()

        if self._task is not None:
            await self._task
            self._task = None
