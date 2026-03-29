from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_start_onboarding_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Начать",
        callback_data="onboarding:start",
    )
    builder.adjust(1)
    return builder.as_markup()


def get_onboarding_goal_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="Направление",
        callback_data="onboarding:goal:direction",
    )
    builder.button(
        text="Ритм",
        callback_data="onboarding:goal:rhythm",
    )
    builder.button(
        text="Себя понять",
        callback_data="onboarding:goal:self",
    )
    builder.button(
        text="Новая сфера",
        callback_data="onboarding:goal:income",
    )

    builder.adjust(1)
    return builder.as_markup()


def get_onboarding_energy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="Мало сил",
        callback_data="onboarding:energy:low",
    )
    builder.button(
        text="Средне",
        callback_data="onboarding:energy:medium",
    )
    builder.button(
        text="Нормально",
        callback_data="onboarding:energy:high",
    )

    builder.adjust(1)
    return builder.as_markup()


def get_onboarding_time_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="15 минут",
        callback_data="onboarding:time:15",
    )
    builder.button(
        text="30 минут",
        callback_data="onboarding:time:30",
    )
    builder.button(
        text="1 час+",
        callback_data="onboarding:time:60",
    )

    builder.adjust(1)
    return builder.as_markup()


def get_direction_choice_keyboard(directions: list[dict[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for index, direction in enumerate(directions[:5]):
        title = direction.get("title", "").strip()[:24]
        if not title:
            continue

        builder.button(
            text=title,
            callback_data=f"direction:choose:{index}",
        )

    builder.adjust(1)
    return builder.as_markup()


def get_payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="Оплатить 299 ₽",
        url=payment_url,
    )
    builder.button(
        text="Проверить оплату",
        callback_data="payment:check",
    )

    builder.adjust(1)
    return builder.as_markup()
