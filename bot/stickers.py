from __future__ import annotations

import random


STICKERS: dict[str, list[dict[str, str]]] = {
    "welcome": [
        {
            "key": "welcome_1",
            "file_id": "CAACAgIAAxkBAAFF8sRpyVQEgzeZW_8YMHwSaVOMvRHh6wACDgADobYRCKW5cu3wl5UWOgQ",
            "file_unique_id": "AgADDgADobYRCA",
            "note": "Приветствие / первый вход",
        },
        {
            "key": "welcome_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант приветствия",
        },
    ],
    "onboarding_start": [
        {
            "key": "onboarding_start_1",
            "file_id": "CAACAgIAAxkBAAFF8tFpyVQ4yrpjGzlnwYwHqmX0FXiT_gAC5pMAAsf3-EmcESHuA_l1XToE",
            "file_unique_id": "AgAD5pMAAsf3-Ek",
            "note": "Начало онбординга",
        },
        {
            "key": "onboarding_start_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант начала онбординга",
        },
    ],
    "thinking": [
        {
            "key": "thinking_1",
            "file_id": "CAACAgIAAxkBAAFF8sJpyVP6v5IaTZOqLFCA-PHbVA9Q-AACSqIAAq0egUum6frZ9WA51ToE",
            "file_unique_id": "AgADSqIAAq0egUs",
            "note": "Пока бот думает / анализирует",
        },
        {
            "key": "thinking_2",
            "file_id": "CAACAgIAAxkBAAFF8sxpyVQsvuoC_ajsKtPTuTZAVeZcAgACZ5QAArs_gEsFOW96CLDvyjoE",
            "file_unique_id": "AgADZ5QAArs_gEs",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "direction_found": [
        {
            "key": "direction_found_1",
            "file_id": "CAACAgIAAxkBAAFF8t1pyVSbP65z8XuGXvHbVhCtjfRJRgACOgADobYRCBvFr5Ov1gHjOgQ",
            "file_unique_id": "AgADOgADobYRCA",
            "note": "Нашли направления",
        },
        {
            "key": "direction_found_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "direction_chosen": [
        {
            "key": "direction_chosen_1",
            "file_id": "CAACAgIAAxkBAAFF8shpyVQPEbcL8ZolkWUUfNlfzjY6BwACygAD3yHsB8qiHcKruWJZOgQ",
            "file_unique_id": "AgADygAD3yHsBw",
            "note": "Пользователь выбрал направление",
        },
        {
            "key": "direction_chosen_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "first_step": [
        {
            "key": "first_step_1",
            "file_id": "",
            "file_unique_id": "",
            "note": "Выдали первый шаг",
        },
        {
            "key": "first_step_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "progress_small": [
        {
            "key": "progress_small_1",
            "file_id": "CAACAgIAAxkBAAFF82ppyVmw7bkpqLyynqo8PjMKhpeMLAAC-JYAAg7NgEsxl1SEff1gkzoE",
            "file_unique_id": "AgAD-JYAAg7NgEs",
            "note": "Небольшой прогресс",
        },
        {
            "key": "progress_small_2",
            "file_id": "",
            "file_unique_id": "",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "progress_good": [
        {
            "key": "progress_good_1",
            "file_id": "CAACAgIAAxkBAAFF825pyVnYZHYGc3O1IWdCgiPFicfizgACEQADefZkEQ-RSAEy6T7iOgQ",
            "file_unique_id": "AgADEQADefZkEQ",
            "note": "Хороший прогресс",
        },
        {
            "key": "progress_good_2",
            "file_id": "CAACAgIAAxkBAAFF8r1pyVPWw1hML_4xvgMuiTwzQFGK2gAC548AAi4vYUmq4OLbodyIoDoE",
            "file_unique_id": "AgAD548AAi4vYUk",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "burnout_soft": [
        {
            "key": "burnout_soft_1",
            "file_id": "CAACAgIAAxkBAAFBnJVpfyBNIKAAAY7dGeZmU8iTOWannAMAAoYAA6G2EQgSSSl5HRrphjgE",
            "file_unique_id": "AgADhgADobYRCA",
            "note": "Мягкий контакт при просадке",
        },
        {
            "key": "burnout_soft_2",
            "file_id": "CAACAgIAAxkBAAFF8s5pyVQy6YcopB4FDGCwstCEyfy8KAACXowAAqUdiUkqW0_eNl16tzoE",
            "file_unique_id": "AgADXowAAqUdiUk",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "followup_live": [
        {
            "key": "followup_live_1",
            "file_id": "CAACAgIAAxkBAAFF8sZpyVQLmg1dXXzYChzGC7LSY7wcRgACxwAD3yHsBxn5t4Yarw6DOgQ",
            "file_unique_id": "AgADxwAD3yHsBw",
            "note": "Живой follow-up",
        },
        {
            "key": "followup_live_2",
            "file_id": "CAACAgIAAxkBAAFF8tppyVSRX7iKJCWmSrQcjEhADjdlkwACMAADobYRCOGeMptDndplOgQ",
            "file_unique_id": "AgADMAADobYRCA",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "push_soft": [
        {
            "key": "push_soft_1",
            "file_id": "",
            "file_unique_id": "",
            "note": "Аккуратный пинок в действие",
        },
        {
            "key": "push_soft_2",
            "file_id": "CAACAgIAAxkBAAFF83RpyVnpaNH9eOP0swboZgVmyNTOSwACMwADefZkES5SqLYG97sCOgQ",
            "file_unique_id": "AgADMwADefZkEQ",
            "note": "Доп. вариант этого же сценария",
        },
    ],
    "error_soft": [
        {
            "key": "error_soft_1",
            "file_id": "CAACAgIAAxkBAAFF8r9pyVPhd0GntVN9L8RdcsuMzZIUvwACDAADefZkEXr2_sSb0Zc4OgQ",
            "file_unique_id": "AgADDAADefZkEQ",
            "note": "Что-то пошло не так",
        },
        {
            "key": "error_soft_2",
            "file_id": "",
            "file_unique_id": "",
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
