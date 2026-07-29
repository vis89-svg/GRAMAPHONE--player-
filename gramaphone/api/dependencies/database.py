from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from api.config import settings
from api.models import Base


db_url = settings.DATABASE_URL

_connect_args = {}
if "sqlite" in db_url:
    _connect_args["check_same_thread"] = False
else:
    parsed = urlparse(db_url)
    params = parse_qs(parsed.query)
    ssl_mode = params.pop("sslmode", None)
    if ssl_mode:
        _connect_args["ssl"] = ssl_mode[0]
        parsed = parsed._replace(query=urlencode(params, doseq=True))
        db_url = urlunparse(parsed)

engine = create_async_engine(
    db_url,
    echo=settings.DEBUG,
    poolclass=NullPool if settings.APP_ENV == "test" else None,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    await engine.dispose()


@asynccontextmanager
async def db_session():
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
