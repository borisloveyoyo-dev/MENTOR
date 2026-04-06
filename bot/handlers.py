import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy import select

from bot.keyboards import (
    get_delete_data_confirm_keyboard,
    get_direction_choice_keyboard,
    get_payment_keyboard,
)
from bot.stickers import get_random_sticker_file_id
from bot.texts import (
    DEFAULT_REPLY_TEXT,
    DIRECTION_CHOICE_TEXT,
    DIRECTION_CHOSEN_TEXT_TEMPLATE,
    FIRST_STEP_INTRO_TEXT,
    ONBOARDING_ABOUT_TEXT,
    ONBOARDING_ALREADY_STARTED_TEXT,
    ONBOARDING_FINISH_TEXT,
    ONBOARDING_NAME_TEXT,
    ONBOARDING_Q1_TEXT,
    ONBOARDING_Q2_TEXT,
    ONBOARDING_Q3_TEXT,
    ONBOARDING_Q4_TEXT,
    WELCOME_TEXT,
)
from db.database import async_session_maker
from db.models import Payment, Subscription, User, UserProfile, UserTask
from services.ai_service import AIService, AIServiceError
from services.mentor_service import (
    MentorServiceError,
    analyze_user_profile_and_save,
    build_state_reply,
    detect_user_state_from_text,
    generate_first_task_for_user,
    get_latest_pending_task_title,
    get_saved_profile_directions,
    save_user_selected_direction,
)
from services.payment_service import PaymentServiceError, create_payment_link
from services.task_review_service import (
    TaskReviewServiceError,
    review_photo_task_submission,
    review_voice_task_submission,
)
from services.task_submission_service import save_task_submission_review
from services.telegram_media_service import (
    TelegramMediaService,
    TelegramMediaServiceError,
)

router = Router()
logger = logging.getLogger(__name__)

SUBSCRIPTION_PRICE_RUB = "299.00"
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_TARIFF_CODE = "monthly_299"

DEBUG_STICKER_ADMIN_IDS = {1041899060}

PAYWALL_TEXT = (
    "Ты уже вошел в движение.\n\n"
    "Чтобы я вел тебя дальше, нужен доступ на месяц.\n"
    "Оплачивай — и идем дальше."
)


def utcnow() -> datetime:
    return datetime.utcnow()


def random_next_followup_at() -> datetime:
    return utcnow() + timedelta(
        hours=random.randint(6, 12),
        minutes=random.randint(0, 59),
    )


def normalize_name(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    return cleaned[:32]


def get_display_name(user: User | None) -> str:
    if user is None:
        return ""
    return (user.first_name or "").strip()


def build_action_push() -> str:
    variants = [
        "Не зависаем. Просто заходим в действие.",
        "Все. Хватит крутить это в голове. Начинаем делать.",
        "Идем руками, не размышлениями.",
        "Ну все, пошел рабочий дым 😏",
    ]
    return random.choice(variants)


def build_easier_reply(task_title: str | None, task_description: str | None) -> str:
    if not task_title or not task_description:
        return (
            "Сейчас не вижу активный шаг.\n\n"
            "Когда будет конкретная задача, я смогу разрезать ее мельче."
        )

    action_lines: list[str] = []
    in_how_section = False

    for raw_line in task_description.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.lower().startswith("как сделать:"):
            in_how_section = True
            continue

        if in_how_section:
            if line.startswith("- "):
                action_lines.append(line[2:].strip())
                continue

            if line.lower().startswith("что может помочь:") or line.lower().startswith(
                "как понять, что шаг сделан:"
            ):
                break

    first_action = action_lines[0] if action_lines else None

    if first_action:
        return (
            f"Окей. Режем мельче.\n\n"
            f"Текущий шаг:\n— {task_title}\n\n"
            f"Сейчас сделай только вот это:\n{first_action}\n\n"
            "Не весь шаг. Только этот кусок."
        )

    return (
        f"Окей. Режем мельче.\n\n"
        f"Текущий шаг:\n— {task_title}\n\n"
        "Сейчас не пытайся сделать все.\n"
        "Открой задачу, зайди в нее на 5–10 минут и добей только самый легкий кусок."
    )


def build_review_reply(
    *,
    review_status: str,
    summary: str,
    strengths: list[str],
    what_to_fix: list[str],
) -> str:
    clean_summary = summary.strip()

    if review_status == "done":
        if strengths:
            return (
                f"{clean_summary}\n\n"
                f"Вот что тут уже реально работает:\n— {strengths[0]}"
            )
        return clean_summary

    if review_status == "partial":
        if strengths:
            return (
                f"{clean_summary}\n\n"
                f"Очень неплохо. Вот что тут уже можно брать дальше:\n— {strengths[0]}"
            )
        return clean_summary

    if strengths:
        return (
            f"{clean_summary}\n\n"
            f"Но вот этот кусок у тебя уже живой:\n— {strengths[0]}"
        )

    return clean_summary


def build_followup_after_review(
    *,
    review_status: str,
    next_step_hint: str,
) -> str:
    if review_status == "done":
        return (
            "Хорошо.\n"
            "На это уже можно опираться.\n"
            "Собираю следующий проход."
        )

    if review_status == "partial":
        return (
            "Очень неплохо.\n"
            f"Сейчас добей вот это:\n{next_step_hint}"
        )

    return (
        "Слушай, ты хотя бы не завис и что-то прислал ��\n"
        "Но сам шаг нам был нужен чуть для другого.\n"
        f"Давай добьем вот это:\n{next_step_hint}"
    )


def is_meaningful_text(text: str | None) -> bool:
    if text is None:
        return False
    return bool(text.strip())


def extract_display_name(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    first_line = raw.splitlines()[0].strip()

    separators = [",", "—", "-", ";", ":"]
    for sep in separators:
        if sep in first_line:
            first_line = first_line.split(sep)[0].strip()

    words = first_line.split()
    if not words:
        return ""

    candidate = " ".join(words[:2])
    return normalize_name(candidate)


def build_sticker_debug_reply(message: Message) -> str:
    if message.sticker is None:
        return "Стикер не найден."

    sticker = message.sticker
    parts = [
        "Поймал стикер. Вот его данные:",
        "",
        f"emoji: {sticker.emoji or '-'}",
        f"set_name: {sticker.set_name or '-'}",
        f"file_id: {sticker.file_id}",
        f"file_unique_id: {sticker.file_unique_id}",
        f"width: {sticker.width}",
        f"height: {sticker.height}",
        f"is_animated: {sticker.is_animated}",
        f"is_video: {sticker.is_video}",
        f"type: {getattr(sticker, 'type', '-')}",
    ]
    return "\n".join(parts)


async def send_optional_sticker(message: Message, pack_name: str) -> None:
    sticker_id = get_random_sticker_file_id(pack_name)
    if not sticker_id:
        logger.info("sticker_skip_empty_pack pack=%s", pack_name)
        return

    try:
        await message.answer_sticker(sticker_id)
        logger.info(
            "sticker_sent pack=%s chat_id=%s user_id=%s",
            pack_name,
            message.chat.id if message.chat else None,
            message.from_user.id if message.from_user else None,
        )
    except Exception:
        logger.exception(
            "sticker_send_failed pack=%s chat_id=%s user_id=%s",
            pack_name,
            message.chat.id if message.chat else None,
            message.from_user.id if message.from_user else None,
        )


async def send_optional_sticker_callback(callback: CallbackQuery, pack_name: str) -> None:
    if callback.message is None:
        logger.info(
            "sticker_callback_skip_no_message pack=%s user_id=%s",
            pack_name,
            callback.from_user.id if callback.from_user else None,
        )
        return

    sticker_id = get_random_sticker_file_id(pack_name)
    if not sticker_id:
        logger.info("sticker_skip_empty_pack pack=%s", pack_name)
        return

    try:
        await callback.message.answer_sticker(sticker_id)
        logger.info(
            "sticker_sent_callback pack=%s chat_id=%s user_id=%s",
            pack_name,
            callback.message.chat.id if callback.message else None,
            callback.from_user.id if callback.from_user else None,
        )
    except Exception:
        logger.exception(
            "sticker_send_callback_failed pack=%s chat_id=%s user_id=%s",
            pack_name,
            callback.message.chat.id if callback.message else None,
            callback.from_user.id if callback.from_user else None,
        )


async def human_answer(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    min_delay: float = 1.0,
    max_delay: float = 2.0,
) -> None:
    delay = random.uniform(min_delay, max_delay)
    async with ChatActionSender(
        bot=message.bot,
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
    ):
        await asyncio.sleep(delay)
        await message.answer(text, reply_markup=reply_markup)


async def human_callback_answer(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    min_delay: float = 1.0,
    max_delay: float = 2.0,
) -> None:
    if callback.message is None:
        return

    delay = random.uniform(min_delay, max_delay)
    async with ChatActionSender(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        action=ChatAction.TYPING,
    ):
        await asyncio.sleep(delay)
        await callback.message.answer(text, reply_markup=reply_markup)


def build_compact_task_text(task: dict) -> str:
    lines: list[str] = []

    lines.append(f"Первый шаг:\n{task['task_title']}")
    lines.append("")
    lines.append(task["step_description"].strip())

    why_text = (task.get("why_this_step") or "").strip()
    if why_text:
        lines.append("")
        lines.append("Зачем это нужно:")
        lines.append(why_text)

    how_to_do_it = task.get("how_to_do_it") or []
    if how_to_do_it:
        lines.append("")
        lines.append("Как сделать:")
        for index, item in enumerate(how_to_do_it, start=1):
            lines.append(f"{index}. {item}")

    recommended_tools = task.get("recommended_tools") or []
    if recommended_tools:
        lines.append("")
        lines.append("Что может помочь:")
        for item in recommended_tools:
            lines.append(f"— {item}")

    success_criteria = (task.get("success_criteria") or "").strip()
    if success_criteria:
        lines.append("")
        lines.append("Когда будет готово — пришли результат.")
        lines.append(success_criteria)

    return "\n".join(lines).strip()


async def get_or_create_user(message: Message) -> User | None:
    if message.from_user is None:
        return None

    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                last_user_message_at=utcnow(),
            )
            session.add(user)
            await session.flush()
            logger.info(
                "user_created telegram_user_id=%s username=%s",
                message.from_user.id,
                message.from_user.username,
            )
        else:
            user.username = message.from_user.username
            user.last_name = message.from_user.last_name

            if not (user.first_name or "").strip():
                user.first_name = message.from_user.first_name

            user.last_user_message_at = utcnow()
            user.updated_at = utcnow()
            logger.info(
                "user_touched user_id=%s telegram_user_id=%s",
                user.id,
                message.from_user.id,
            )

        await session.commit()
        return user


async def get_or_create_profile_by_user_id(user_id: int) -> UserProfile:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = UserProfile(user_id=user_id, onboarding_step="start")
            session.add(profile)
            await session.flush()
            await session.commit()
            logger.info("profile_created user_id=%s onboarding_step=start", user_id)
            return profile

        return profile


async def get_user_and_profile_by_telegram_id(
    telegram_user_id: int,
) -> tuple[User | None, UserProfile | None]:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = user_result.scalar_one_or_none()

        if user is None:
            return None, None

        profile_result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()

        if profile is None:
            profile = UserProfile(user_id=user.id, onboarding_step="start")
            session.add(profile)
            await session.commit()
            logger.info("profile_created_late user_id=%s onboarding_step=start", user.id)
            return user, profile

        return user, profile


async def update_profile_fields(user_id: int, **fields) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = UserProfile(user_id=user_id)
            session.add(profile)
            await session.flush()

        for field_name, field_value in fields.items():
            setattr(profile, field_name, field_value)

        profile.updated_at = utcnow()
        await session.commit()
        logger.info("profile_updated user_id=%s fields=%s", user_id, list(fields.keys()))


async def update_user_display_name(user_id: int, display_name: str) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return

        user.first_name = display_name
        user.updated_at = utcnow()
        await session.commit()
        logger.info("user_display_name_updated user_id=%s display_name=%s", user_id, display_name)


async def touch_user_activity(user_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return

        user.last_user_message_at = utcnow()
        user.updated_at = utcnow()
        user.push_explanation_due_at = None

        if user.is_onboarding_completed and user.selected_direction:
            user.next_followup_at = random_next_followup_at()

        await session.commit()
        logger.info("user_activity_touched user_id=%s", user_id)


async def set_initial_followup_schedule(user_id: int) -> None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return

        user.last_user_message_at = utcnow()
        user.next_followup_at = random_next_followup_at()
        user.push_explanation_due_at = None
        user.updated_at = utcnow()

        await session.commit()
        logger.info("initial_followup_set user_id=%s", user_id)


async def mark_onboarding_completed(user_id: int) -> None:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        profile_result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()

        if user is not None:
            user.is_onboarding_completed = True
            user.updated_at = utcnow()

        if profile is not None:
            profile.onboarding_step = "completed"
            profile.onboarding_completed_at = utcnow()
            profile.updated_at = utcnow()

        await session.commit()
        logger.info("onboarding_completed user_id=%s", user_id)


async def has_active_subscription(user_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.status == "active")
            .order_by(Subscription.ends_at.desc(), Subscription.id.desc())
        )
        subscription = result.scalars().first()

        if subscription is None:
            return False

        if subscription.ends_at is None:
            return False

        return subscription.ends_at > utcnow()


async def has_completed_any_task(user_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserTask.id)
            .where(UserTask.user_id == user_id)
            .where(UserTask.status == "done")
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


async def get_latest_pending_task(user_id: int) -> UserTask | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserTask)
            .where(UserTask.user_id == user_id)
            .where(UserTask.status == "pending")
            .order_by(UserTask.assigned_at.desc(), UserTask.id.desc())
        )
        return result.scalars().first()


async def should_require_payment(user_id: int) -> bool:
    if await has_active_subscription(user_id):
        return False

    current_task = await get_latest_pending_task(user_id)
    if current_task is not None:
        return False

    return await has_completed_any_task(user_id)


async def create_month_payment_for_user(user_id: int) -> str:
    payment_result = await create_payment_link(
        user_id=user_id,
        amount_rub=SUBSCRIPTION_PRICE_RUB,
        description="Доступ к наставнику на 30 дней",
        tariff_code=SUBSCRIPTION_TARIFF_CODE,
    )

    async with async_session_maker() as session:
        payment = Payment(
            user_id=user_id,
            yookassa_payment_id=payment_result.payment_id,
            amount_value=payment_result.amount_value,
            amount_currency=payment_result.amount_currency,
            status=payment_result.status or "pending",
            payment_url=payment_result.confirmation_url,
            description="Доступ к наставнику на 30 дней",
        )
        session.add(payment)
        await session.commit()

    logger.info("payment_created user_id=%s payment_id=%s", user_id, payment_result.payment_id)
    return payment_result.confirmation_url


async def send_payment_required_message(message: Message, user_id: int) -> None:
    try:
        payment_url = await create_month_payment_for_user(user_id)
    except PaymentServiceError:
        logger.exception("payment_required_payment_service_error user_id=%s", user_id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "С оплатой сейчас не получилось.\n\nПопробуй еще раз чуть позже.",
        )
        return
    except Exception:
        logger.exception("payment_required_unexpected_error user_id=%s", user_id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я сейчас споткнулся на создании оплаты.\n\nПопробуй еще раз чуть позже.",
        )
        return

    await human_answer(
        message,
        PAYWALL_TEXT,
        reply_markup=get_payment_keyboard(payment_url),
        min_delay=1.6,
        max_delay=2.8,
    )
    logger.info("payment_required_sent user_id=%s", user_id)


async def send_payment_required_callback(callback: CallbackQuery, user_id: int) -> None:
    if callback.message is None:
        await callback.answer("Не получилось открыть оплату", show_alert=True)
        return

    try:
        payment_url = await create_month_payment_for_user(user_id)
    except PaymentServiceError:
        logger.exception("payment_required_callback_payment_service_error user_id=%s", user_id)
        await send_optional_sticker_callback(callback, "error_soft")
        await human_callback_answer(
            callback,
            "С оплатой сейчас не получилось.\n\nПопробуй еще раз чуть позже.",
        )
        await callback.answer()
        return
    except Exception:
        logger.exception("payment_required_callback_unexpected_error user_id=%s", user_id)
        await send_optional_sticker_callback(callback, "error_soft")
        await human_callback_answer(
            callback,
            "Я сейчас споткнулся на создании оплаты.\n\nПопробуй еще раз чуть позже.",
        )
        await callback.answer()
        return

    await human_callback_answer(
        callback,
        PAYWALL_TEXT,
        reply_markup=get_payment_keyboard(payment_url),
        min_delay=1.6,
        max_delay=2.8,
    )
    await callback.answer()
    logger.info("payment_required_callback_sent user_id=%s", user_id)


async def mark_latest_pending_task_completed(user_id: int) -> str | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserTask)
            .where(UserTask.user_id == user_id)
            .where(UserTask.status == "pending")
            .order_by(UserTask.assigned_at.desc(), UserTask.id.desc())
        )
        task = result.scalars().first()

        if task is None:
            return None

        task.status = "done"
        task.completed_at = utcnow()
        await session.commit()
        logger.info("task_completed user_id=%s task_id=%s", user_id, task.id)
        return task.title.strip() if task.title else None


async def create_next_task_for_user(
    *,
    user_id: int,
    selected_direction: str,
    current_task_title: str,
    current_task_description: str,
    review_summary: str,
    strengths: list[str],
    what_to_fix: list[str],
    next_step_mode: str,
    next_step_hint: str,
) -> dict:
    async with async_session_maker() as session:
        user_result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        profile_result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()

        if user is None or profile is None:
            raise MentorServiceError("Не удалось подготовить следующий шаг")

        ai_service = AIService()
        plan = await ai_service.generate_next_step_plan(
            selected_direction=selected_direction,
            current_task_title=current_task_title,
            current_task_description=current_task_description,
            review_summary=review_summary,
            strengths=strengths,
            what_to_fix=what_to_fix,
            next_step_mode=next_step_mode,
            next_step_hint=next_step_hint,
            current_income_source=profile.current_income_source,
            free_time_style=profile.free_time_style,
            appreciation_reason=profile.appreciation_reason,
            help_request_reason=profile.help_request_reason,
            about_text=profile.about_text,
        )

        task_description_lines: list[str] = []
        task_description_lines.append(plan.step_description)
        task_description_lines.append("")
        task_description_lines.append(
            f"Почему сейчас лучше начать с этого: {plan.why_this_step}"
        )
        task_description_lines.append("")
        task_description_lines.append("Как сделать:")
        for item in plan.how_to_do_it:
            task_description_lines.append(f"- {item}")

        if plan.recommended_tools:
            task_description_lines.append("")
            task_description_lines.append("Что может помочь:")
            for item in plan.recommended_tools:
                task_description_lines.append(f"- {item}")

        task_description_lines.append("")
        task_description_lines.append(
            f"Как понять, что шаг сделан: {plan.success_criteria}"
        )

        new_task = UserTask(
            user_id=user_id,
            title=plan.step_title,
            description="\n".join(task_description_lines),
            status="pending",
            difficulty_mode="normal",
        )
        session.add(new_task)
        await session.commit()

        logger.info("next_task_created user_id=%s task_title=%s", user_id, plan.step_title)

        return {
            "task_title": plan.step_title,
            "step_description": plan.step_description,
            "why_this_step": plan.why_this_step,
            "how_to_do_it": plan.how_to_do_it,
            "recommended_tools": plan.recommended_tools,
            "success_criteria": plan.success_criteria,
        }


async def delete_user_and_all_data_by_telegram_id(telegram_user_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return False

        await session.delete(user)
        await session.commit()
        logger.info("user_deleted telegram_user_id=%s user_id=%s", telegram_user_id, user.id)
        return True


async def show_or_generate_directions(message: Message, user: User) -> None:
    directions = await get_saved_profile_directions(user.id)

    if directions:
        await send_optional_sticker(message, "direction_found")
        await human_answer(
            message,
            "Хорошо, вот что тебе может подойти:",
            min_delay=1.0,
            max_delay=1.8,
        )
        await human_answer(
            message,
            DIRECTION_CHOICE_TEXT,
            reply_markup=get_direction_choice_keyboard(directions),
            min_delay=1.2,
            max_delay=2.0,
        )
        logger.info("directions_shown_saved user_id=%s count=%s", user.id, len(directions))
        return

    await send_optional_sticker(message, "thinking")
    await human_answer(
        message,
        "Сейчас быстро посмотрю, куда тебе лучше зайти сначала.",
        min_delay=1.3,
        max_delay=2.4,
    )

    try:
        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        ):
            await asyncio.sleep(random.uniform(3.0, 5.0))
            _analysis_text, directions = await analyze_user_profile_and_save(user.id)

        await send_optional_sticker(message, "direction_found")
        await human_answer(
            message,
            "Хорошо, вот что тебе может подойти:",
            min_delay=1.0,
            max_delay=1.8,
        )
        await human_answer(
            message,
            DIRECTION_CHOICE_TEXT,
            reply_markup=get_direction_choice_keyboard(directions),
            min_delay=1.2,
            max_delay=2.0,
        )
        logger.info("directions_generated user_id=%s count=%s", user.id, len(directions))
    except (AIServiceError, MentorServiceError):
        logger.exception("directions_generate_known_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Профиль у меня есть.\n\nС вариантами сейчас не получилось. Попробуй еще раз через /start.",
        )
    except Exception:
        logger.exception("directions_generate_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я сейчас споткнулся на подборе направлений.\n\nПопробуй еще раз через /start.",
        )


async def handle_task_submission_photo(message: Message, user: User) -> bool:
    if not user.selected_direction:
        return False

    current_task = await get_latest_pending_task(user.id)
    if current_task is None:
        return False

    if not message.photo:
        return False

    largest_photo = message.photo[-1]
    media_service = TelegramMediaService(message.bot)

    try:
        photo_payload = await media_service.prepare_photo_for_review(
            file_id=largest_photo.file_id,
        )
        review = await review_photo_task_submission(
            user_id=user.id,
            task_title=current_task.title,
            task_description=current_task.description,
            selected_direction=user.selected_direction,
            photo_file_url=photo_payload.file_url,
        )

        await save_task_submission_review(
            user_id=user.id,
            task_id=current_task.id,
            submission_type="photo",
            telegram_file_id=largest_photo.file_id,
            review_status=review.review_status,
            review_summary=review.summary,
            strengths=review.strengths,
            what_to_fix=review.what_to_fix,
            next_step_mode=review.next_step_mode,
            next_step_hint=review.next_step_hint,
        )
        logger.info(
            "photo_review_saved user_id=%s task_id=%s review_status=%s",
            user.id,
            current_task.id,
            review.review_status,
        )
    except (TelegramMediaServiceError, TaskReviewServiceError, AIServiceError):
        logger.exception("photo_review_known_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я увидел фото, но сейчас не смог нормально проверить шаг.\n\nПопробуй прислать еще раз чуть позже.",
        )
        return True
    except Exception:
        logger.exception("photo_review_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я сейчас споткнулся на проверке фото.\n\nПопробуй еще раз чуть позже.",
        )
        return True

    await send_optional_sticker(message, "progress_small")
    await human_answer(
        message,
        build_review_reply(
            review_status=review.review_status,
            summary=review.summary,
            strengths=review.strengths,
            what_to_fix=review.what_to_fix,
        ),
        min_delay=2.2,
        max_delay=4.2,
    )

    if review.review_status != "done":
        await human_answer(
            message,
            build_followup_after_review(
                review_status=review.review_status,
                next_step_hint=review.next_step_hint,
            ),
            min_delay=1.2,
            max_delay=2.2,
        )
        return True

    await mark_latest_pending_task_completed(user.id)
    await human_answer(
        message,
        build_followup_after_review(
            review_status=review.review_status,
            next_step_hint=review.next_step_hint,
        ),
        min_delay=1.2,
        max_delay=2.2,
    )

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return True

    try:
        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        ):
            await asyncio.sleep(random.uniform(3.0, 5.0))
            next_task = await create_next_task_for_user(
                user_id=user.id,
                selected_direction=user.selected_direction,
                current_task_title=current_task.title,
                current_task_description=current_task.description,
                review_summary=review.summary,
                strengths=review.strengths,
                what_to_fix=review.what_to_fix,
                next_step_mode=review.next_step_mode,
                next_step_hint=review.next_step_hint,
            )

        await send_optional_sticker(message, "first_step")
        await human_answer(
            message,
            build_compact_task_text(next_task),
            min_delay=1.8,
            max_delay=3.0,
        )
        await human_answer(
            message,
            build_action_push(),
            min_delay=1.0,
            max_delay=1.8,
        )
    except Exception:
        logger.exception("photo_review_next_task_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Шаг я засчитал, но на следующем куске сейчас споткнулся.\n\nПопробуй нажать /next чуть позже.",
        )

    return True


async def handle_task_submission_voice(message: Message, user: User) -> bool:
    if not user.selected_direction:
        return False

    current_task = await get_latest_pending_task(user.id)
    if current_task is None:
        return False

    if not message.voice:
        return False

    media_service = TelegramMediaService(message.bot)
    voice_local_path: str | None = None

    try:
        voice_payload = await media_service.prepare_voice_for_review(
            file_id=message.voice.file_id,
        )
        voice_local_path = voice_payload.local_path

        review = await review_voice_task_submission(
            user_id=user.id,
            task_title=current_task.title,
            task_description=current_task.description,
            selected_direction=user.selected_direction,
            voice_file_path=voice_local_path,
        )

        await save_task_submission_review(
            user_id=user.id,
            task_id=current_task.id,
            submission_type="voice",
            telegram_file_id=message.voice.file_id,
            transcript_text=review.voice_transcript,
            review_status=review.review_status,
            review_summary=review.summary,
            strengths=review.strengths,
            what_to_fix=review.what_to_fix,
            next_step_mode=review.next_step_mode,
            next_step_hint=review.next_step_hint,
        )
        logger.info(
            "voice_review_saved user_id=%s task_id=%s review_status=%s",
            user.id,
            current_task.id,
            review.review_status,
        )
    except (TelegramMediaServiceError, TaskReviewServiceError, AIServiceError):
        logger.exception("voice_review_known_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я услышал голосовое, но сейчас не смог нормально проверить шаг.\n\nПопробуй прислать еще раз чуть позже.",
        )
        return True
    except Exception:
        logger.exception("voice_review_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я сейчас споткнулся на проверке голосового.\n\nПопробуй еще раз чуть позже.",
        )
        return True
    finally:
        media_service.cleanup_local_file(voice_local_path)

    await send_optional_sticker(message, "progress_small")
    await human_answer(
        message,
        build_review_reply(
            review_status=review.review_status,
            summary=review.summary,
            strengths=review.strengths,
            what_to_fix=review.what_to_fix,
        ),
        min_delay=2.2,
        max_delay=4.2,
    )

    if review.review_status != "done":
        await human_answer(
            message,
            build_followup_after_review(
                review_status=review.review_status,
                next_step_hint=review.next_step_hint,
            ),
            min_delay=1.2,
            max_delay=2.2,
        )
        return True

    await mark_latest_pending_task_completed(user.id)
    await human_answer(
        message,
        build_followup_after_review(
            review_status=review.review_status,
            next_step_hint=review.next_step_hint,
        ),
        min_delay=1.2,
        max_delay=2.2,
    )

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return True

    try:
        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        ):
            await asyncio.sleep(random.uniform(3.0, 5.0))
            next_task = await create_next_task_for_user(
                user_id=user.id,
                selected_direction=user.selected_direction,
                current_task_title=current_task.title,
                current_task_description=current_task.description,
                review_summary=review.summary,
                strengths=review.strengths,
                what_to_fix=review.what_to_fix,
                next_step_mode=review.next_step_mode,
                next_step_hint=review.next_step_hint,
            )

        await send_optional_sticker(message, "first_step")
        await human_answer(
            message,
            build_compact_task_text(next_task),
            min_delay=1.8,
            max_delay=3.0,
        )
        await human_answer(
            message,
            build_action_push(),
            min_delay=1.0,
            max_delay=1.8,
        )
    except Exception:
        logger.exception("voice_review_next_task_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Шаг я засчитал, но на следующем куске сейчас споткнулся.\n\nПопробуй нажать /next чуть позже.",
        )

    return True


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    logger.info(
        "handler_cmd_start user_id=%s username=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
        message.text,
    )

    user = await get_or_create_user(message)
    if user is None:
        await message.answer("Не получилось определить тебя в Telegram. Попробуй еще раз.")
        return

    profile = await get_or_create_profile_by_user_id(user.id)

    if profile.onboarding_step not in ("start", "completed"):
        await human_answer(message, ONBOARDING_ALREADY_STARTED_TEXT)
        return

    if user.is_onboarding_completed:
        if user.selected_direction:
            if await should_require_payment(user.id):
                await send_payment_required_message(message, user.id)
                return

            display_name = get_display_name(user)
            if display_name:
                await human_answer(
                    message,
                    f"С возвращением, {display_name}.\n\nМы с тобой идем в сторону: {user.selected_direction}",
                )
            else:
                await human_answer(
                    message,
                    f"С возвращением.\n\nМы с тобой идем в сторону: {user.selected_direction}",
                )
            return

        await show_or_generate_directions(message, user)
        return

    await update_profile_fields(
        user_id=user.id,
        onboarding_step="q0_name",
    )
    await send_optional_sticker(message, "welcome")
    await human_answer(
        message,
        WELCOME_TEXT,
        min_delay=1.2,
        max_delay=2.4,
    )


@router.message(Command("done"))
async def cmd_done(message: Message) -> None:
    logger.info(
        "handler_cmd_done user_id=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if message.from_user is None:
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return

    completed_title = await mark_latest_pending_task_completed(user.id)
    if completed_title is None:
        await human_answer(
            message,
            "Сейчас не вижу активный шаг.\n\nЕсли хочешь, жми /next — соберу следующий.",
        )
        return

    await send_optional_sticker(message, "progress_good")
    await human_answer(
        message,
        "Вот, уже хорошо.\n\n"
        f"Закрыл шаг:\n— {completed_title}\n\n"
        "Темп не расплескивай. Когда будешь готов — жми /next.",
    )


@router.message(Command("stuck"))
async def cmd_stuck(message: Message) -> None:
    logger.info(
        "handler_cmd_stuck user_id=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if message.from_user is None:
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return

    await update_profile_fields(
        user_id=user.id,
        energy_level="low",
        burnout_flag=False,
    )

    task_title = await get_latest_pending_task_title(user.id)
    await send_optional_sticker(message, "burnout_soft")
    await human_answer(message, build_state_reply("stuck", task_title))


@router.message(Command("easier"))
async def cmd_easier(message: Message) -> None:
    logger.info(
        "handler_cmd_easier user_id=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if message.from_user is None:
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return

    task = await get_latest_pending_task(user.id)
    await human_answer(
        message,
        build_easier_reply(
            task.title if task else None,
            task.description if task else None,
        ),
    )


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    logger.info(
        "handler_cmd_next user_id=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if message.from_user is None:
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if not user.is_onboarding_completed:
        await human_answer(message, "Сначала дойдем до конца анкеты через /start.")
        return

    if not user.selected_direction:
        await show_or_generate_directions(message, user)
        return

    current_task = await get_latest_pending_task(user.id)
    if current_task is not None:
        await human_answer(
            message,
            "У нас еще висит текущий шаг.\n\n"
            f"Вот он:\n— {current_task.title}\n\n"
            "Если уже сделал — жми /done.\n"
            "Если тяжело — жми /easier.\n"
            "Если сделал руками — можешь еще прислать фото или голосовое, я посмотрю.",
            min_delay=1.2,
            max_delay=2.0,
        )
        return

    if await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return

    await human_answer(
        message,
        "Хорошо. Собираю следующий кусок.",
        min_delay=1.0,
        max_delay=1.8,
    )

    try:
        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        ):
            await asyncio.sleep(random.uniform(3.0, 5.0))
            next_task = await generate_first_task_for_user(user.id)

        await send_optional_sticker(message, "first_step")
        await human_answer(
            message,
            build_compact_task_text(next_task),
            min_delay=1.8,
            max_delay=3.0,
        )
        await human_answer(
            message,
            build_action_push(),
            min_delay=1.0,
            max_delay=1.8,
        )
    except (AIServiceError, MentorServiceError):
        logger.exception("cmd_next_known_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Сейчас не получилось собрать следующий шаг.\n\nПопробуй еще раз чуть позже.",
        )
    except Exception:
        logger.exception("cmd_next_unexpected_error user_id=%s", user.id)
        await send_optional_sticker(message, "error_soft")
        await human_answer(
            message,
            "Я сейчас споткнулся на следующем шаге.\n\nПопробуй еще раз чуть позже.",
        )


@router.message(Command("delete_me"))
async def cmd_delete_me(message: Message) -> None:
    logger.info(
        "handler_cmd_delete_me user_id=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if message.from_user is None:
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await human_answer(
            message,
            "Я пока не вижу у тебя сохраненных данных.",
        )
        return

    await human_answer(
        message,
        "Точно удалить твои данные?\n\n"
        "Уйдет профиль, анкета, задачи, подписка, платежи и история внутри бота.\n"
        "Это действие не откатить.",
        reply_markup=get_delete_data_confirm_keyboard(),
    )


@router.callback_query(F.data == "user:delete:confirm")
async def user_delete_confirm(callback: CallbackQuery) -> None:
    logger.info(
        "callback_user_delete_confirm user_id=%s data=%r",
        callback.from_user.id if callback.from_user else None,
        callback.data,
    )

    if callback.from_user is None:
        await callback.answer()
        return

    deleted = await delete_user_and_all_data_by_telegram_id(callback.from_user.id)

    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)

        if deleted:
            await human_callback_answer(
                callback,
                "Готово.\n\nВсе твои данные внутри бота удалены.\nЕсли захочешь начать заново — просто жми /start.",
            )
        else:
            await human_callback_answer(
                callback,
                "Я не нашел, что удалять.\n\nЕсли захочешь начать заново — жми /start.",
            )

    await callback.answer("Данные удалены" if deleted else "Нечего удалять")


@router.callback_query(F.data == "user:delete:cancel")
async def user_delete_cancel(callback: CallbackQuery) -> None:
    logger.info(
        "callback_user_delete_cancel user_id=%s data=%r",
        callback.from_user.id if callback.from_user else None,
        callback.data,
    )

    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await human_callback_answer(callback, "Окей, ничего не удаляю.")

    await callback.answer("Удаление отменено")


@router.callback_query(F.data == "onboarding:start")
async def onboarding_start(callback: CallbackQuery) -> None:
    logger.info(
        "callback_onboarding_start user_id=%s data=%r",
        callback.from_user.id if callback.from_user else None,
        callback.data,
    )

    if callback.from_user is None:
        await callback.answer()
        return

    user, _profile = await get_user_and_profile_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Не удалось найти пользователя", show_alert=True)
        return

    await update_profile_fields(
        user_id=user.id,
        onboarding_step="q0_name",
    )

    if callback.message is not None:
        await send_optional_sticker_callback(callback, "onboarding_start")
        await callback.message.edit_text(ONBOARDING_NAME_TEXT)

    await callback.answer()


@router.callback_query(F.data == "payment:check")
async def payment_check(callback: CallbackQuery) -> None:
    logger.info(
        "callback_payment_check user_id=%s data=%r",
        callback.from_user.id if callback.from_user else None,
        callback.data,
    )

    if callback.from_user is None:
        await callback.answer()
        return

    user, _profile = await get_user_and_profile_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Не удалось найти пользователя", show_alert=True)
        return

    if await has_active_subscription(user.id):
        if callback.message is not None:
            await human_callback_answer(
                callback,
                "Оплату вижу.\n\nТеперь можем идти дальше.",
            )
        await callback.answer("Оплата найдена")
        return

    if callback.message is not None:
        await human_callback_answer(
            callback,
            "Оплату пока не вижу.\n\nЕсли уже оплатил, подожди немного и нажми еще раз.",
        )

    await callback.answer("Пока не вижу оплату", show_alert=False)


@router.callback_query(F.data.startswith("direction:choose:"))
async def direction_choose(callback: CallbackQuery) -> None:
    logger.info(
        "callback_direction_choose user_id=%s data=%r",
        callback.from_user.id if callback.from_user else None,
        callback.data,
    )

    if callback.from_user is None:
        await callback.answer()
        return

    user, _profile = await get_user_and_profile_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Не удалось найти пользователя", show_alert=True)
        return

    directions = await get_saved_profile_directions(user.id)
    if not directions:
        await callback.answer("Список направлений пока не найден", show_alert=True)
        return

    try:
        index = int(callback.data.split(":")[-1])
    except (TypeError, ValueError):
        await callback.answer("Не удалось разобрать выбор", show_alert=True)
        return

    if index < 0 or index >= len(directions):
        await callback.answer("Такого варианта уже нет", show_alert=True)
        return

    chosen_direction = directions[index]
    chosen_title = chosen_direction["title"]
    chosen_description = chosen_direction["description"]

    await save_user_selected_direction(user.id, chosen_title)
    await set_initial_followup_schedule(user.id)

    if callback.message is None:
        await callback.answer("Выбор сохранен")
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await send_optional_sticker_callback(callback, "direction_chosen")

    await human_callback_answer(
        callback,
        DIRECTION_CHOSEN_TEXT_TEMPLATE.format(direction=chosen_title),
        min_delay=1.2,
        max_delay=2.0,
    )
    await human_callback_answer(
        callback,
        f"Почему это может тебе зайти:\n\n{chosen_description}",
        min_delay=1.0,
        max_delay=1.8,
    )

    try:
        async with ChatActionSender(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            action=ChatAction.TYPING,
        ):
            await asyncio.sleep(random.uniform(3.0, 5.0))
            first_task = await generate_first_task_for_user(user.id)

        await human_callback_answer(
            callback,
            FIRST_STEP_INTRO_TEXT,
            min_delay=1.0,
            max_delay=1.6,
        )
        await send_optional_sticker_callback(callback, "first_step")
        await human_callback_answer(
            callback,
            build_compact_task_text(first_task),
            min_delay=1.8,
            max_delay=3.0,
        )
        await human_callback_answer(
            callback,
            build_action_push(),
            min_delay=1.0,
            max_delay=1.8,
        )
    except (AIServiceError, MentorServiceError):
        logger.exception("direction_choose_known_error user_id=%s", user.id)
        await send_optional_sticker_callback(callback, "error_soft")
        await human_callback_answer(
            callback,
            "Выбор сохранил.\n\nС первым шагом сейчас не получилось. Но направление уже на месте.",
        )
    except Exception:
        logger.exception("direction_choose_unexpected_error user_id=%s", user.id)
        await send_optional_sticker_callback(callback, "error_soft")
        await human_callback_answer(
            callback,
            "Выбор сохранил.\n\nНа первом шаге я сейчас споткнулся. Но сам выбор не потерян.",
        )

    await callback.answer("Выбор сохранен")


@router.message(F.sticker)
async def handle_sticker_debug(message: Message) -> None:
    logger.info(
        "handler_sticker_debug user_id=%s username=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )

    if message.from_user is None or message.sticker is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    logger.info(
        "sticker_debug_received user_id=%s set_name=%s emoji=%s file_id=%s file_unique_id=%s",
        message.from_user.id,
        message.sticker.set_name,
        message.sticker.emoji,
        message.sticker.file_id,
        message.sticker.file_unique_id,
    )

    if message.from_user.id not in DEBUG_STICKER_ADMIN_IDS:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await message.answer(build_sticker_debug_reply(message))


@router.message(F.photo)
async def handle_photo_submission(message: Message) -> None:
    logger.info(
        "handler_photo user_id=%s username=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )

    if message.from_user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if not user.is_onboarding_completed:
        await human_answer(message, "Фото вижу. Сначала дойдем до конца анкеты через /start.")
        return

    handled = await handle_task_submission_photo(message, user)
    if handled:
        return

    await human_answer(
        message,
        "Фото получил.\n\nКогда у нас будет активный шаг, я смогу проверить по нему результат.",
    )


@router.message(F.voice)
async def handle_voice_submission(message: Message) -> None:
    logger.info(
        "handler_voice user_id=%s username=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )

    if message.from_user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    user, _profile = await get_user_and_profile_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    if not user.is_onboarding_completed:
        await human_answer(
            message,
            "Голосовое услышал. Сначала дойдем до конца анкеты через /start.",
        )
        return

    handled = await handle_task_submission_voice(message, user)
    if handled:
        return

    await human_answer(
        message,
        "Голосовое получил.\n\nКогда у нас будет активный шаг, я смогу проверить по нему результат.",
    )


@router.message()
async def handle_any_message(message: Message) -> None:
    logger.info(
        "handler_any_message user_id=%s username=%s text=%r content_type=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
        message.text,
        getattr(message, "content_type", None),
    )

    if message.from_user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    user, profile = await get_user_and_profile_by_telegram_id(message.from_user.id)

    if user is None or profile is None:
        logger.info(
            "handler_any_message_user_or_profile_missing telegram_user_id=%s",
            message.from_user.id,
        )
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    text = (message.text or "").strip()

    if profile.onboarding_step == "q0_name":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Напиши одним сообщением, как тебя называть и в каком роде к тебе обращаться.",
            )
            return

        display_name = extract_display_name(text)
        if len(display_name) < 2:
            await human_answer(message, "Давай чуть понятнее. Хотя бы 2 символа.")
            return

        await update_user_display_name(user.id, display_name)
        await update_profile_fields(
            user_id=user.id,
            onboarding_step="q1_income",
        )
        await human_answer(message, f"Отлично, {display_name}.", min_delay=0.8, max_delay=1.4)
        await human_answer(message, ONBOARDING_Q1_TEXT, min_delay=1.0, max_delay=1.8)
        return

    if profile.onboarding_step == "q1_income":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Напиши коротко, сколько у тебя сейчас реально есть времени на это.",
            )
            return

        await update_profile_fields(
            user_id=user.id,
            current_income_source=text,
            onboarding_step="q2_free_time",
        )
        await human_answer(message, ONBOARDING_Q2_TEXT, min_delay=1.0, max_delay=1.8)
        return

    if profile.onboarding_step == "q2_free_time":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Напиши коротко, к чему тебя вообще тянет.",
            )
            return

        await update_profile_fields(
            user_id=user.id,
            free_time_style=text,
            onboarding_step="q3_appreciation",
        )
        await human_answer(message, ONBOARDING_Q3_TEXT, min_delay=1.0, max_delay=1.8)
        return

    if profile.onboarding_step == "q3_appreciation":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Напиши коротко, что ты уже пробовал делать.",
            )
            return

        await update_profile_fields(
            user_id=user.id,
            appreciation_reason=text,
            onboarding_step="q4_help_requests",
        )
        await human_answer(message, ONBOARDING_Q4_TEXT, min_delay=1.0, max_delay=1.8)
        return

    if profile.onboarding_step == "q4_help_requests":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Напиши коротко, на что в себе ты уже можешь опереться.",
            )
            return

        await update_profile_fields(
            user_id=user.id,
            help_request_reason=text,
            onboarding_step="awaiting_about",
            onboarding_about_requested=True,
        )
        await human_answer(message, ONBOARDING_ABOUT_TEXT, min_delay=1.2, max_delay=2.0)
        return

    if profile.onboarding_step == "awaiting_about":
        if not is_meaningful_text(text):
            await human_answer(
                message,
                "Пришли это текстом. Пары абзацев хватит.",
            )
            return

        await update_profile_fields(
            user_id=user.id,
            about_text=text,
            onboarding_step="completed",
        )
        await mark_onboarding_completed(user.id)

        await human_answer(message, ONBOARDING_FINISH_TEXT, min_delay=1.0, max_delay=1.8)
        await show_or_generate_directions(message, user)
        return

    if user.is_onboarding_completed and not user.selected_direction:
        await show_or_generate_directions(message, user)
        return

    if user.is_onboarding_completed and await should_require_payment(user.id):
        await send_payment_required_message(message, user.id)
        return

    if user.is_onboarding_completed:
        detected_state = detect_user_state_from_text(text)

        if detected_state is not None:
            await update_profile_fields(
                user_id=user.id,
                energy_level=detected_state["energy_level"],
                burnout_flag=detected_state["burnout_flag"],
            )

            state_code = detected_state["state_code"]

            if state_code in {"burnout", "exhausted", "overwhelmed"}:
                await send_optional_sticker(message, "burnout_soft")
            elif state_code in {"progress", "done", "small_progress"}:
                await send_optional_sticker(message, "progress_small")
            elif state_code in {"good_progress", "result"}:
                await send_optional_sticker(message, "progress_good")

            task_title = await get_latest_pending_task_title(user.id)
            reply_text = build_state_reply(
                state_code,
                task_title,
            )
            await human_answer(message, reply_text, min_delay=1.0, max_delay=2.0)
            return

    await message.answer(DEFAULT_REPLY_TEXT)
