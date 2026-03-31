from __future__ import annotations

import random


STICKERS: dict[str, list[dict[str, str]]] = {
    "welcome": [
        {
            "key": "welcome_1",
            "file_id": "AAMCAgADGQEAAUXy0WnJVDjKumMbOWfBjAeqZfQVeJP-AALmkwACx_f4SZwRIe4D-XVdAQAHbQADOgQ",
            "file_unique_id": "AQAD5pMAAsf3-Ely",
            "note": "Приветствие / первый вход",
        },
        {
            "key": "welcome_2",
            "file_id": "AAMCAgADGQEAAUXyzGnJVCy-6gL9qOwq09O5NkBV5lwCAAJnlAACuz-ASwU5b3oIsO_KAQAHbQADOgQ",
            "file_unique_id": "AQADZ5QAArs_gEty",
            "note": "Доп. вариант приветствия",
        },
    ],
    "onboarding_start": [
        {
            "key": "onboarding_start_1",
            "file_id": "AAMCAgADGQEAAUXyzGnJVCy-6gL9qOwq09O5NkBV5lwCAAJnlAACuz-ASwU5b3oIsO_KAQAHbQADOgQ",
            "file_unique_id": "AQADZ5QAArs_gEty",
            "note": "Начало онбординга",
        },
        {
            "key": "onboarding_start_2",
            "file_id": "AAMCAgADGQEAAUXy0WnJVDjKumMbOWfBjAeqZfQVeJP-AALmkwACx_f4SZwRIe4D-XVdAQAHbQADOgQ",
            "file_unique_id": "AQAD5pMAAsf3-Ely",
            "note": "Доп. вариант начала онбординга",
        },
    ],
    "thinking": [
        {
            "key": "thinking_1",
            "file_id": "AAMCAgADGQEAAUXyvWnJU9bDWEwv_jG-Ay6JPDNAUYraAALnjwACLi9hSarg4tuh3IigAQAHbQADOgQ",
            "file_unique_id": "AQAD548AAi4vYUly",
            "note": "Пока бот думает / анализирует",
        },
        {
            "key": "thinking_2",
            "file_id": "AAMCAgADGQEAAUXywmnJU_q_khpNk6osUID48dtUD1D4AAJKogACrR6BS6bp-tn1YDnVAQAHbQADOgQ",
            "file_unique_id": "AQADSqIAAq0egUty",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "direction_found": [
        {
            "key": "direction_found_1",
            "file_id": "AAMCAgADGQEAAUXyvWnJU9bDWEwv_jG-Ay6JPDNAUYraAALnjwACLi9hSarg4tuh3IigAQAHbQADOgQ",
            "file_unique_id": "AQAD548AAi4vYUly",
            "note": "Нашли направления",
        },
        {
            "key": "direction_found_2",
            "file_id": "AAMCAgADGQEAAUXywmnJU_q_khpNk6osUID48dtUD1D4AAJKogACrR6BS6bp-tn1YDnVAQAHbQADOgQ",
            "file_unique_id": "AQADSqIAAq0egUty",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "direction_chosen": [
        {
            "key": "direction_chosen_1",
            "file_id": "AAMCAgADGQEAAUXzbmnJWdhkdgZzc7UhZ0KCI8WJx-LOAAIRAAN59mQRD5FIATLpPuIBAAdtAAM6BA",
            "file_unique_id": "AQADEQADefZkEXI",
            "note": "Пользователь выбрал направление",
        },
        {
            "key": "direction_chosen_2",
            "file_id": "AAMCAgADGQEAAUXzamnJWbDtuSmovLKeqjw-MwqGl4wsAAL4lgACDs2ASzGXVIR9_WCTAQAHbQADOgQ",
            "file_unique_id": "AQAD-JYAAg7NgEty",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "first_step": [
        {
            "key": "first_step_1",
            "file_id": "AAMCAgADGQEAAUXzaGnJWaw4OzR75ONTkxXc41UhEK0eAAI5kAACtX-AS5Z4kRONfDRDAQAHbQADOgQ",
            "file_unique_id": "AQADOZAAArV_gEty",
            "note": "Выдали первый шаг",
        },
        {
            "key": "first_step_2",
            "file_id": "AAMCAgADGQEAAUXyyGnJVA8RtwvxmiWRZRR82V_ONjoHAALKAAPfIewHyqIdwqu5YlkBAAdtAAM6BA",
            "file_unique_id": "AQADygAD3yHsB3I",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "progress_small": [
        {
            "key": "progress_small_1",
            "file_id": "AAMCAgADGQEAAUXyyGnJVA8RtwvxmiWRZRR82V_ONjoHAALKAAPfIewHyqIdwqu5YlkBAAdtAAM6BA",
            "file_unique_id": "AQADygAD3yHsB3I",
            "note": "Небольшой прогресс",
        },
        {
            "key": "progress_small_2",
            "file_id": "AAMCAgADGQEAAUXy3WnJVJs_rnPxe4Ze8dtWEK2N9ElGAAI6AAOhthEIG8Wvk6_WAeMBAAdtAAM6BA",
            "file_unique_id": "AQADOgADobYRCHI",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "progress_good": [
        {
            "key": "progress_good_1",
            "file_id": "AAMCAgADGQEAAUXyxGnJVASDN5lb_xgwfBJpU4y9EeHrAAIOAAOhthEIpbly7fCXlRYBAAdtAAM6BA",
            "file_unique_id": "AQADDgADobYRCHI",
            "note": "Хороший прогресс",
        },
        {
            "key": "progress_good_2",
            "file_id": "AAMCAgADGQEAAUXyyGnJVA8RtwvxmiWRZRR82V_ONjoHAALKAAPfIewHyqIdwqu5YlkBAAdtAAM6BA",
            "file_unique_id": "AQADygAD3yHsB3I",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "burnout_soft": [
        {
            "key": "burnout_soft_1",
            "file_id": "AAMCAgADGQEAAUXyxmnJVAuaDV1dfNgKHMYLstJjvBxGAALHAAPfIewHGfm3hhqvDoMBAAdtAAM6BA",
            "file_unique_id": "AQADxwAD3yHsB3I",
            "note": "Мягкий контакт при просадке",
        },
        {
            "key": "burnout_soft_2",
            "file_id": "AAMCAgADGQEAAUXzdGnJWelo0f144_SzBuhmBWbI1M5LAAIzAAN59mQRLlKotgb3uwIBAAdtAAM6BA",
            "file_unique_id": "AQADMwADefZkEXI",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "followup_live": [
        {
            "key": "followup_live_1",
            "file_id": "AAMCAgADGQEAAUXzaGnJWaw4OzR75ONTkxXc41UhEK0eAAI5kAACtX-AS5Z4kRONfDRDAQAHbQADOgQ",
            "file_unique_id": "AQADOZAAArV_gEty",
            "note": "Живой follow-up",
        },
        {
            "key": "followup_live_2",
            "file_id": "AAMCAgADGQEAAUXyxmnJVAuaDV1dfNgKHMYLstJjvBxGAALHAAPfIewHGfm3hhqvDoMBAAdtAAM6BA",
            "file_unique_id": "AQADxwAD3yHsB3I",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "push_soft": [
        {
            "key": "push_soft_1",
            "file_id": "AAMCAgADGQEAAUXzaGnJWaw4OzR75ONTkxXc41UhEK0eAAI5kAACtX-AS5Z4kRONfDRDAQAHbQADOgQ",
            "file_unique_id": "AQADOZAAArV_gEty",
            "note": "Аккуратный пинок в действие",
        },
        {
            "key": "push_soft_2",
            "file_id": "AAMCAgADGQEAAUXyyGnJVA8RtwvxmiWRZRR82V_ONjoHAALKAAPfIewHyqIdwqu5YlkBAAdtAAM6BA",
            "file_unique_id": "AQADygAD3yHsB3I",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "error_soft": [
        {
            "key": "error_soft_1",
            "file_id": "AAMCAgADGQEAAUXyv2nJU-F3Qae1U30vxF1yy4zNkhS_AAIMAAN59mQRevb-xJvRlzgBAAdtAAM6BA",
            "file_unique_id": "AQADDAADefZkEXI",
            "note": "Что-то пошло не так",
        },
        {
            "key": "error_soft_2",
            "file_id": "AAMCAgADGQEAAUXy2mnJVJFfuIokJaZKtByMSEAON2WTAAIwAAOhthEI4Z4ym0Od2mUBAAdtAAM6BA",
            "file_unique_id": "AQADMAADobYRCHI",
            "note": "Доп. вариант этого же сценария",
        },
    ],
}


def get_sticker_pack_keys() -> list[str]:
    return list(STICKERS.keys())


def get_stickers_by_pack(pack_name: str) -> list[dict[str, str]]:
    return STICKERS.get(pack_name, [])


def get_random_sticker(pack_name: str) -> dict[str, str] | None:
    stickers = [
        item
        for item in STICKERS.get(pack_name, [])
        if item.get("file_id", "").strip()
    ]
    if not stickers:
        return None
    return random.choice(stickers)


def get_random_sticker_file_id(pack_name: str) -> str | None:
    sticker = get_random_sticker(pack_name)
    if sticker is None:
        return None
    return sticker.get("file_id") or None


def get_random_sticker_unique_id(pack_name: str) -> str | None:
    sticker = get_random_sticker(pack_name)
    if sticker is None:
        return None
    return sticker.get("file_unique_id") or None


def get_sticker_by_key(sticker_key: str) -> dict[str, str] | None:
    for stickers in STICKERS.values():
        for sticker in stickers:
            if sticker.get("key") == sticker_key:
                return sticker
    return None


def get_sticker_file_id_by_key(sticker_key: str) -> str | None:
    sticker = get_sticker_by_key(sticker_key)
    if sticker is None:
        return None
    return sticker.get("file_id") or None
