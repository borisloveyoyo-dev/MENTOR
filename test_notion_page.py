import asyncio

from services.notion_service import smoke_test_notion_day_plan_page


async def main() -> None:
    result = await smoke_test_notion_day_plan_page()
    print("PAGE_ID:", result.page_id)
    print("URL:", result.url)


if __name__ == "__main__":
    asyncio.run(main())

