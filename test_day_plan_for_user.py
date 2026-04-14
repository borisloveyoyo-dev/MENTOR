import argparse
import asyncio

from services.day_plan_service import create_personal_day_plan_page_for_telegram_user


DEFAULT_COVER_URL = "https://www.dropbox.com/scl/fi/zeoyyuidhg4z16d0ga0vg/.png?rlkey=u3lhyurgd6dzymr9jr30b0guv&st=quf198w9&raw=1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Создать персональную Notion-страницу day plan для пользователя по telegram_user_id."
    )
    parser.add_argument(
        "--telegram-id",
        type=int,
        required=True,
        help="Telegram user id пользователя",
    )
    parser.add_argument(
        "--cover-url",
        type=str,
        default=DEFAULT_COVER_URL,
        help="Публичный cover image URL для Notion",
    )
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    result = await create_personal_day_plan_page_for_telegram_user(
        telegram_user_id=args.telegram_id,
        cover_url=args.cover_url,
    )

    print("USER_ID:", result.user_id)
    print("TELEGRAM_USER_ID:", result.telegram_user_id)
    print("PAGE_TITLE:", result.page_title)
    print("PAGE_ID:", result.page_id)
    print("PAGE_URL:", result.page_url)
    print("")
    print("INTRO:")
    print(result.generated_plan.intro)
    print("")
    print("SECTIONS:")
    for section in result.generated_plan.sections:
        print("-", section["title"])
        for line in section["lines"]:
            print("  *", line)
        if section["note"]:
            print("  note:", section["note"])
        if section["quote"]:
            print("  quote:", section["quote"])
        print("")
    print("CLOSING_NOTE:")
    print(result.generated_plan.closing_note)


if __name__ == "__main__":
    asyncio.run(main())
