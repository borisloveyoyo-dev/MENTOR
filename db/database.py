import os
import ssl

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()


class Base(DeclarativeBase):
    pass


def build_database_url() -> str:
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    return (
        f"postgresql+asyncpg://{db_user}:{db_password}"
        f"@{db_host}:{db_port}/{db_name}"
    )


def build_connect_args() -> dict:
    ssl_mode = (os.getenv("DB_SSL_MODE") or os.getenv("PGSSLMODE") or "disable").strip().lower()

    if ssl_mode in {"", "disable", "false", "0", "off"}:
        return {"ssl": False}

    if ssl_mode in {"require", "prefer", "allow"}:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return {"ssl": ssl_context}

    if ssl_mode in {"verify-ca", "verify_full", "verify-full"}:
        ssl_context = ssl.create_default_context()
        ssl_root_cert = (os.getenv("DB_SSL_ROOT_CERT") or "").strip()

        if ssl_root_cert:
            ssl_context.load_verify_locations(cafile=ssl_root_cert)

        if ssl_mode == "verify-ca":
            ssl_context.check_hostname = False
        else:
            ssl_context.check_hostname = True

        ssl_context.verify_mode = ssl.CERT_REQUIRED
        return {"ssl": ssl_context}

    return {"ssl": False}


DATABASE_URL = build_database_url()
CONNECT_ARGS = build_connect_args()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=CONNECT_ARGS,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
