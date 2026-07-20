"""对象存储抽象层 — MinIO 上传 / 下载 / URL 生成"""

from datetime import timedelta
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

# ──── MinIO 客户端 ────
_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)


def ensure_bucket(bucket_name: str | None = None) -> None:
    """确保存储桶存在，不存在则创建。"""
    name = bucket_name or settings.MINIO_BUCKET
    if not _client.bucket_exists(name):
        _client.make_bucket(name)


def upload_file(
    file_data: bytes,
    object_name: str,
    content_type: str = "application/octet-stream",
    bucket_name: str | None = None,
) -> str:
    """上传文件到 MinIO。

    Args:
        file_data: 文件的字节内容
        object_name: MinIO 中的对象名（路径），如 "images/2024/abc123.jpg"
        content_type: MIME 类型
        bucket_name: 存储桶名，默认使用配置中的桶

    Returns:
        对象的完整路径，如 "/detection-platform/images/2024/abc123.jpg"
    """
    bucket = bucket_name or settings.MINIO_BUCKET
    ensure_bucket(bucket)

    _client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=BytesIO(file_data),
        length=len(file_data),
        content_type=content_type,
    )

    return f"/{bucket}/{object_name}"


def get_file_url(object_path: str, expires: int = 3600) -> str:
    """生成临时下载 URL（预签名 URL）。

    Args:
        object_path: 对象完整路径，如 "/detection-platform/images/abc.jpg"
        expires: URL 有效期（秒），默认 1 小时

    Returns:
        预签名 URL 字符串
    """
    # 去掉开头的 "/" 和桶名前缀
    path = object_path.lstrip("/")
    parts = path.split("/", 1)
    if len(parts) != 2:
        return ""

    bucket, object_name = parts[0], parts[1]
    return _client.presigned_get_object(
        bucket, object_name, expires=timedelta(seconds=expires)
    )


def delete_file(object_path: str) -> None:
    """从 MinIO 删除文件。

    Args:
        object_path: 对象完整路径
    """
    path = object_path.lstrip("/")
    parts = path.split("/", 1)
    if len(parts) != 2:
        return

    bucket, object_name = parts[0], parts[1]
    try:
        _client.remove_object(bucket, object_name)
    except S3Error:
        pass  # 文件不存在时静默忽略
