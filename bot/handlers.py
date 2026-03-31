from datetime import datetime, timedelta
import random

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy import select

from bot.keyboards import (
    get_direction_choice_keyboard,
    get_payment_keyboard,
    get_start_onboarding_keyboard,
)
from bot.stickers import get_random_sticker_file_id
from bot.texts import (
    DEFAULT_REPLY_TEXT,
    DIRECTION_CHOICE_TEXT,
    DIRECTION_CHOSEN_TEXT_TEMPLATE,
    FIRST_STEP_DESCRIPTION_TEMPLATE,
    FIRST_STEP_INTRO_TEXT,
    FIRST_STEP_SUCCESS_TEMPLATE,
    FIRST_STEP_TITLE_TEMPLATE,
    FIRST_STEP_WHY_TEMPLATE,
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
from db.models import Payment, Subscription, User, UserProfile
from services.ai_service import AIServiceError
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

router = Router()

SUBSCRIPTION_PRICE_RUB = "299.00"
SUBSCRIPTION_DAYS = 30
SUBSCRIPTION_TARIFF_CODE = "monthly_299"
PAYWALL_TEXT = (
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

    name = (user.first_name or "").strip()
    return name


def build_action_push() -> str:
    variants = [
        "А теперь не задаемся вопросами и начинаем делать.",
        "Все. Хватит крутить это в голове. Начинаем делать.",
        "Не зависаем. Просто заходим в действие.",
        "Идем руками, не размышлениями.",
    ]
    return random.choice(variants)


async def send_optional_sticker(message: Message, pack_name: str) -> None:
    sticker_id = get_random_sticker_file_id(pack_name)
    if not sticker_id:
        return

    try:
        await message.answer_sticker(sticker_id)
    except Exception:
        pass


async def send_optional_sticker_callback(callback: CallbackQuery, pack_name: str) -> None:
    if callback.message is None:
        return

    sticker_id = get_random_sticker_file_id(pack_name)
    if not sticker_id:
        return

    try:
        await callback.message.answer_sticker(sticker_id)
    except Exception:
        pass


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
        else:
            user.username = message.from_user.username
            user.last_name = message.from_user.last_name

            if not (user.first_name or "").strip():
                user.first_name = message.from_user.first_name

            user.last_user_message_at = utcnow()
            user.updated_at = utcnow()

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

    return payment_result.confirmation_url


async def send_payment_required_message(message: Message, user_id: int) -> None:
    try:
        payment_url = await create_month_payment_for_user(user_id)
    except PaymentServiceError:
        await send_optional_sticker(message, "error_soft")
        await message.answer(
            "С оплатой сейчас не получилось.\n\nПопробуй еще раз чуть позже."
        )
        return
    except Exception:
        await send_optional_sticker(message, "error_soft")
        await message.answer(
            "Я сейчас споткнулся на создании оплаты.\n\nПопробуй еще раз чуть позже."
        )
        return

    await message.answer(
        PAYWALL_TEXT,
        reply_markup=get_payment_keyboard(payment_url),
    )


async def send_payment_required_callback(callback: CallbackQuery, user_id: int) -> None:
    if callback.message is None:
        await callback.answer("Не получилось открыть оплату", show_alert=True)
        return

    try:
        payment_url = await create_month_payment_for_user(user_id)
    except PaymentServiceError:
        await send_optional_sticker_callback(callback, "error_soft")
        await callback.message.answer(
            "С оплатой сейчас не получилось.\n\nПопробуй еще раз чуть позже."
        )
        await callback.answer()
        return
    except Exception:
        await send_optional_sticker_callback(callback, "error_soft")
        await callback.message.answer(
            "Я сейчас споткнулся на создании оплаты.\n\nПопробуй еще раз чуть позже."
        )
        await callback.answer()
        return

    await callback.message.answer(
        PAYWALL_TEXT,
        reply_markup=get_payment_keyboard(payment_url),
    )
    await callback.answer()


def is_meaningful_text(text: str | None) -> bool:
    if text is None:
        return False
    return bool(text.strip())


async def send_typing(message: Message) -> ChatActionSender:
    return ChatActionSender(
        bot=message.bot,
        chat_id=message.chat.id,
        action=ChatAction.TYPING,
    )


async def show_or_generate_directions(message: Message, user: User) -> None:
    if not await has_active_subscription(user.id):
        await send_payment_required_message(message, user.id)
        return

    directions = await get_saved_profile_directions(user.id)

    if directions:
        await send_optional_sticker(message, "direction_found")
        await message.answer("Я уже собрал тебе варианты.")
        await message.answer(
            DIRECTION_CHOICE_TEXT,
            reply_markup=get_direction_choice_keyboard(directions),
        )
        return

    await send_optional_sticker(message, "thinking")
    await message.answer("Сейчас быстро посмотрю, куда тебе лучше зайти сначала.")

    try:
        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.TYPING,
        ):
            analysis_text, directions = await analyze_user_profile_and_save(user.id)

        await send_optional_sticker(message, "direction_found")
        await message.answer(analysis_text)
        await message.answer(
            DIRECTION_CHOICE_TEXT,
            reply_markup=get_direction_choice_keyboard(directions),
        )
    except (AIServiceError, MentorServiceError):
        await send_optional_sticker(message, "error_soft")
        await message.answer(
            "Профиль у меня есть.\n\n"
            "С вариантами сейчас не получилось. Попробуй еще раз через /start."
        )
    except Exception:
        await send_optional_sticker(message, "error_soft")
        await message.answer(
            "Я сейчас споткнулся на подборе направлений.\n\n"
            "Попробуй еще раз через /start."
        )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await get_or_create_user(message)
    if user is None:
        await message.answer("Не получилось определить тебя в Telegram. Попробуй еще раз.")
        return

    profile = await get_or_create_profile_by_user_id(user.id)

    if profile.onboarding_step not in ("start", "completed"):
        await message.answer(ONBOARDING_ALREADY_STARTED_TEXT)
        return

    if user.is_onboarding_completed:
        if user.selected_direction:
            if not await has_active_subscription(user.id):
                await send_payment_required_message(message, user.id)
                return

            display_name = get_display_name(user)
            if display_name:
                await message.answer(
                    f"С возвращением, {display_name}.\n\n"
                    f"Мы с тобой идем в сторону: {user.selected_direction}"
                )
            else:
                await message.answer(
                    "С возвращением.\n\n"
                    f"Мы с тобой идем в сторону: {user.selected_direction}"
                )
            return

        await show_or_generate_directions(message, user)
        return

    await send_optional_sticker(message, "welcome")
    await message.answer(
        WELCOME_TEXT,
        reply_markup=get_start_onboarding_keyboard(),
    )


@router.callback_query(F.data == "onboarding:start")
async def onboarding_start(callback: CallbackQuery) -> None:
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
    if callback.from_user is None:
        await callback.answer()
        return

    user, _profile = await get_user_and_profile_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Не удалось найти пользователя", show_alert=True)
        return

    if await has_active_subscription(user.id):
        if callback.message is not None:
            await callback.message.answer(
                "Оплату вижу.\n\nТеперь можем идти дальше."
            )
        await callback.answer("Оплата найдена")
        return

    if callback.message is not None:
        await callback.message.answer(
            "Оплату пока не вижу.\n\nЕсли уже оплатил, подожди немного и нажми еще раз."
        )

    await callback.answer("Пока не вижу оплату", show_alert=False)


@router.callback_query(F.data.startswith("direction:choose:"))
async def direction_choose(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        await callback.answer()
        return

    user, _profile = await get_user_and_profile_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Не удалось найти пользователя", show_alert=True)
        return

    if not await has_active_subscription(user.id):
        await send_payment_required_callback(callback, user.id)
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

    display_name = get_display_name(user)

    await callback.message.edit_reply_markup(reply_markup=None)
    await send_optional_sticker_callback(callback, "direction_chosen")

    if display_name:
        await callback.message.answer(f"Хорошо, {display_name}.")
    else:
        await callback.message.answer("Хорошо.")

    await callback.message.answer(
        DIRECTION_CHOSEN_TEXT_TEMPLATE.format(direction=chosen_title)
    )
    await callback.message.answer(
        f"Почему это может тебе зайти:\n\n{chosen_description}"
    )

    try:
        async with ChatActionSender(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            action=ChatAction.TYPING,
        ):
            first_task = await generate_first_task_for_user(user.id)

        if first_task.get("short_perspective"):
            await callback.message.answer(first_task["short_perspective"])

        await callback.message.answer(FIRST_STEP_INTRO_TEXT)

        await send_optional_sticker_callback(callback, "first_step")
        await callback.message.answer(
            FIRST_STEP_TITLE_TEMPLATE.format(task_title=first_task["task_title"])
        )
        await callback.message.answer(
            FIRST_STEP_DESCRIPTION_TEMPLATE.format(
                step_description=first_task["step_description"]
            )
        )
        await callback.message.answer(
            FIRST_STEP_WHY_TEMPLATE.format(
                why_this_step=first_task["why_this_step"]
            )
        )

        if first_task["how_to_do_it"]:
            how_lines = "\n".join(
                f"{index + 1}. {item}"
                for index, item in enumerate(first_task["how_to_do_it"])
            )
            await callback.message.answer(
                "Как это сделать:\n\n" + how_lines
            )

        if first_task["recommended_tools"]:
            tool_lines = "\n".join(
                f"— {item}" for item in first_task["recommended_tools"]
            )
            await callback.message.answer(
                "Что может помочь:\n\n" + tool_lines
            )

        await callback.message.answer(
            FIRST_STEP_SUCCESS_TEMPLATE.format(
                success_criteria=first_task["success_criteria"]
            )
        )
        await callback.message.answer(build_action_push())
    except (AIServiceError, MentorServiceError):
        await send_optional_sticker_callback(callback, "error_soft")
        await callback.message.answer(
            "Выбор сохранил.\n\n"
            "С первым шагом сейчас не получилось. Но направление уже на месте."
        )
    except Exception:
        await send_optional_sticker_callback(callback, "error_soft")
        await callback.message.answer(
            "Выбор сохранил.\n\n"
            "На первом шаге я сейчас споткнулся. Но сам выбор не потерян."
        )

    await callback.answer("Выбор сохранен")


@router.message()
async def handle_any_message(message: Message) -> None:
    if message.from_user is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    user, profile = await get_user_and_profile_by_telegram_id(message.from_user.id)

    if user is None or profile is None:
        await message.answer(DEFAULT_REPLY_TEXT)
        return

    await touch_user_activity(user.id)

    text = (message.text or "").strip()

    if profile.onboarding_step == "q0_name":
        if not is_meaningful_text(text):
            await message.answer("Напиши коротко, как к тебе обращаться.")
            return

        display_name = normalize_name(text)
        if len(display_name) < 2:
            await message.answer("Давай чуть понятнее. Хотя бы 2 символа.")
            return

        await update_user_display_name(user.id, display_name)
        await update_profile_fields(
            user_id=user.id,
            onboarding_step="q1_income",
        )
        await message.answer(f"Отлично, {display_name}.")
        await message.answer(ONBOARDING_Q1_TEXT)
        return

    if profile.onboarding_step == "q1_income":
        if not is_meaningful_text(text):
            await message.answer(
                "Напиши коротко, чем ты сейчас зарабатываешь."
            )
            return

        await update_profile_fields(
            user_id=user.id,
            current_income_source=text,
            onboarding_step="q2_free_time",
        )
        await message.answer(ONBOARDING_Q2_TEXT)
        return

    if profile.onboarding_step == "q2_free_time":
        if not is_meaningful_text(text):
            await message.answer(
                "Напиши коротко, как ты обычно проводишь свободное время."
            )
            return

        await update_profile_fields(
            user_id=user.id,
            free_time_style=text,
            onboarding_step="q3_appreciation",
        )
        await message.answer(ONBOARDING_Q3_TEXT)
        return

    if profile.onboarding_step == "q3_appreciation":
        if not is_meaningful_text(text):
            await message.answer(
                "Напиши коротко, за что тебя чаще всего ценят или благодарят."
            )
            return

        await update_profile_fields(
            user_id=user.id,
            appreciation_reason=text,
            onboarding_step="q4_help_requests",
        )
        await message.answer(ONBOARDING_Q4_TEXT)
        return

    if profile.onboarding_step == "q4_help_requests":
        if not is_meaningful_text(text):
            await message.answer(
                "Напиши коротко, с чем к тебе чаще всего приходят за помощью."
            )
            return

        await update_profile_fields(
            user_id=user.id,
            help_request_reason=text,
            onboarding_step="awaiting_about",
            onboarding_about_requested=True,
        )
        await message.answer(ONBOARDING_ABOUT_TEXT)
        return

    if profile.onboarding_step == "awaiting_about":
        if not is_meaningful_text(text):
            await message.answer(
                "Пришли это текстом. Пары абзацев хватит."
            )
            return

        await update_profile_fields(
            user_id=user.id,
            about_text=text,
            onboarding_step="completed",
        )
        await mark_onboarding_completed(user.id)

        await message.answer(ONBOARDING_FINISH_TEXT)
        await message.answer(
            "Онбординг сохранил.\n\n"
            "Дальше уже работаем по подписке."
        )
        await send_payment_required_message(message, user.id)
        return

    if user.is_onboarding_completed and not await has_active_subscription(user.id):
        await send_payment_required_message(message, user.id)
        return

    if user.is_onboarding_completed and not user.selected_direction:
        await show_or_generate_directions(message, user)
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
            await message.answer(reply_text)
            return

    await message.answer(DEFAULT_REPLY_TEXT)
