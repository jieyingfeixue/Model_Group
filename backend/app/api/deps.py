"""API 通用依赖 — get_current_user 注入"""

from app.core.middleware import get_current_user, require_role

__all__ = ["get_current_user", "require_role"]
