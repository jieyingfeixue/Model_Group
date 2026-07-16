"""Redis 连接池 — 提供独立 Redis 客户端，供 security / cache 等模块使用"""

import redis as redis_lib

from app.core.config import settings

# ──── 模块级客户端 ────
_client: redis_lib.Redis | None = None


def get_redis_client() -> redis_lib.Redis:
    """获取 Redis 客户端（模块级单例，用于非请求上下文）。

    使用场景：
    - security.py 中 Token 黑名单操作
    - 后续：标注推理缓存、导出任务状态
    """
    global _client
    if _client is None:
        _client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def get_redis():
    """FastAPI 依赖注入：每个请求生成独立 Redis 连接。

    Usage:
        @router.get("/")
        def endpoint(redis: Redis = Depends(get_redis)):
            ...
    """
    client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        client.close()
