"""安全模块 — bcrypt 密码哈希 + JWT 签发/解码 + Redis Token 黑名单"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.redis import get_redis_client

# ──── bcrypt ────
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """对明文密码进行 bcrypt 哈希"""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码是否与 bcrypt 哈希匹配"""
    return _pwd_context.verify(plain, hashed)


# ──── JWT ────

_ALGORITHM = "HS256"
BLACKLIST_PREFIX = "blacklist:"  # Key 前缀，避免与其他缓存冲突


def _encode_token(data: dict, expires_delta: timedelta) -> str:
    """签发 JWT Token（内部通用）"""
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    to_encode["iat"] = datetime.now(timezone.utc)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    """签发 Access Token，有效期由 settings.ACCESS_TOKEN_EXPIRE_HOURS 控制（默认 24h）"""
    return _encode_token(
        {"sub": str(user_id), "role": role, "type": "access"},
        timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS),
    )


def create_refresh_token(user_id: int) -> str:
    """签发 Refresh Token，有效期由 settings.REFRESH_TOKEN_EXPIRE_DAYS 控制（默认 7d）"""
    return _encode_token(
        {"sub": str(user_id), "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    """解码并校验 JWT Token。

    Returns:
        payload 字典（含 sub、role、type 等字段）

    Raises:
        JWTError: Token 无效、过期或签名不匹配
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])


# ──── Token 黑名单（Redis） ────


def blacklist_token(token: str, ttl: int) -> None:
    """将 Token 加入 Redis 黑名单，ttl 秒后自动过期删除。

    使用场景：
    - 用户登出时吊销 Refresh Token（ttl = 剩余有效期）
    - 角色变更时强制重新登录（吊销该用户所有 Refresh Token）
    """
    get_redis_client().setex(f"{BLACKLIST_PREFIX}{token}", ttl, "1")


def is_token_blacklisted(token: str) -> bool:
    """检查 Token 是否已被加入黑名单"""
    return get_redis_client().exists(f"{BLACKLIST_PREFIX}{token}") > 0


def blacklist_all_user_tokens(user_id: int) -> None:
    """角色变更时调用：将该用户所有已知 Refresh Token 加入黑名单。

    注：当前 Redis 中没有存储"该用户有多少 Token"的映射，此方法为占位，
    后续可配合登录时记录 (user_id → token_keys) 来实现全量吊销。
    """
    # TODO: 记录登录态映射后实现全量吊销
    pass
