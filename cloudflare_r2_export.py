"""Cloudflare R2 helpers for large snapshot exports."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import mimetypes
from pathlib import Path
from urllib.parse import quote


logger = logging.getLogger(__name__)


try:
    import boto3
    from boto3.s3.transfer import TransferConfig

    BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover - runtime only
    boto3 = None
    TransferConfig = None
    BOTO3_AVAILABLE = False


DEFAULT_UPLOAD_PART_SIZE = 16 * 1024 * 1024
DEFAULT_UPLOAD_THREADS = 4
DEFAULT_PRESIGNED_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass
class R2UploadResult:
    bucket: str
    object_key: str
    size_bytes: int
    endpoint_url: str
    download_url: str


def build_r2_endpoint_url(account_id: str) -> str:
    return f"https://{str(account_id).strip()}.r2.cloudflarestorage.com"


def _normalize_public_base_url(public_base_url: str) -> str:
    return str(public_base_url).rstrip("/")


def _build_public_download_url(public_base_url: str, object_key: str) -> str:
    base = _normalize_public_base_url(public_base_url)
    object_path = "/".join(quote(part) for part in str(object_key).split("/"))
    return f"{base}/{object_path}"


def _guess_content_type(source_path: Path) -> str:
    guessed_type, _ = mimetypes.guess_type(str(source_path))
    return guessed_type or "application/octet-stream"


def _build_r2_client(
    *,
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
):
    if not BOTO3_AVAILABLE:
        raise ImportError(
            "Для выгрузки в Cloudflare R2 установите зависимость boto3"
        )

    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=build_r2_endpoint_url(account_id),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _build_transfer_config():
    if TransferConfig is None:
        raise ImportError(
            "Для выгрузки в Cloudflare R2 установите зависимость boto3"
        )

    return TransferConfig(
        multipart_threshold=DEFAULT_UPLOAD_PART_SIZE,
        multipart_chunksize=DEFAULT_UPLOAD_PART_SIZE,
        max_concurrency=DEFAULT_UPLOAD_THREADS,
        use_threads=True,
    )


class _UploadProgressLogger:
    def __init__(self, *, total_bytes: int, object_key: str) -> None:
        self.total_bytes = max(1, int(total_bytes))
        self.object_key = object_key
        self.transferred_bytes = 0
        self.last_logged_percent = -1

    def __call__(self, bytes_amount: int) -> None:
        self.transferred_bytes += int(bytes_amount)
        percent = int((self.transferred_bytes / self.total_bytes) * 100)
        if percent >= self.last_logged_percent + 10 or percent >= 100:
            logger.info("☁️ R2 upload progress %s: %s%%", self.object_key, min(percent, 100))
            self.last_logged_percent = min(percent, 100)


def upload_file_to_r2(
    *,
    source_path: Path,
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    object_key: str,
    public_base_url: str | None = None,
    presigned_ttl_seconds: int = DEFAULT_PRESIGNED_TTL_SECONDS,
) -> R2UploadResult:
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Не найден файл для выгрузки в Cloudflare R2: {source_path}")

    normalized_bucket = str(bucket).strip()
    normalized_object_key = str(object_key).lstrip("/")
    endpoint_url = build_r2_endpoint_url(account_id)
    file_size_bytes = source_path.stat().st_size
    logger.info(
        "☁️ R2 upload start: source=%s bucket=%s key=%s size_mb=%.2f endpoint=%s",
        source_path,
        normalized_bucket,
        normalized_object_key,
        file_size_bytes / (1024 * 1024),
        endpoint_url,
    )

    client = _build_r2_client(
        account_id=account_id,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
    transfer_config = _build_transfer_config()
    extra_args = {
        "ContentType": _guess_content_type(source_path),
    }
    progress_logger = _UploadProgressLogger(
        total_bytes=file_size_bytes,
        object_key=normalized_object_key,
    )

    client.upload_file(
        str(source_path),
        normalized_bucket,
        normalized_object_key,
        ExtraArgs=extra_args,
        Config=transfer_config,
        Callback=progress_logger,
    )

    if public_base_url:
        download_url = _build_public_download_url(public_base_url, normalized_object_key)
    else:
        download_url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": normalized_bucket,
                "Key": normalized_object_key,
            },
            ExpiresIn=int(presigned_ttl_seconds),
        )

    logger.info(
        "✅ R2 upload complete: bucket=%s key=%s size_bytes=%s download_url=%s",
        normalized_bucket,
        normalized_object_key,
        file_size_bytes,
        download_url,
    )

    return R2UploadResult(
        bucket=normalized_bucket,
        object_key=normalized_object_key,
        size_bytes=file_size_bytes,
        endpoint_url=endpoint_url,
        download_url=download_url,
    )
