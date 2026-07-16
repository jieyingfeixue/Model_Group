"""SQLAlchemy 引擎 + 会话工厂 + get_db 依赖"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,       # 连接前检查有效性
    echo=False,               # 生产环境设为 False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """FastAPI 依赖注入：每个请求生成一个独立数据库会话。

    请求成功返回时自动 commit，异常时自动 rollback，请求结束后关闭会话。
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
