"""Google Drive helpers for syncing supplier CSV catalogs into local storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import re
from urllib.parse import parse_qs, urlparse


logger = logging.getLogger(__name__)


try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:  # pragma: no cover - handled by runtime checks
    service_account = None
    build = None
    MediaIoBaseDownload = None
    HttpError = Exception
    GOOGLE_DRIVE_AVAILABLE = False


DRIVE_SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"


@dataclass
class DriveCsvFile:
    file_id: str
    name: str
    modified_time: str
    size_bytes: int = 0


@dataclass
class DriveAccessReport:
    folder_id: str
    csv_count: int
    can_access: bool


def extract_drive_folder_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Не указан URL/ID папки Google Drive")

    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text

    parsed = urlparse(text)
    if not parsed.netloc:
        raise ValueError("Неверный формат ссылки/ID папки Google Drive")

    path_match = re.search(r"/folders/([A-Za-z0-9_-]{10,})", parsed.path)
    if path_match:
        return path_match.group(1)

    query_id = parse_qs(parsed.query).get("id")
    if query_id and query_id[0]:
        return query_id[0]

    raise ValueError("Не удалось извлечь ID папки из ссылки Google Drive")


def _build_drive_service(service_account_info: dict):
    if not GOOGLE_DRIVE_AVAILABLE:
        raise ImportError(
            "Для синхронизации из Google Drive установите зависимости: "
            "google-api-python-client и google-auth"
        )

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=[DRIVE_SCOPE_READONLY],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _list_csv_files(service, folder_id: str) -> list[DriveCsvFile]:
    query = (
        f"'{folder_id}' in parents and trashed = false "
        "and mimeType = 'text/csv'"
    )

    files: list[DriveCsvFile] = []
    page_token = None
    while True:
        try:
            response = service.files().list(
                q=query,
                pageSize=1000,
                fields="nextPageToken, files(id, name, modifiedTime, size)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        except HttpError as e:
            raise PermissionError(f"Google Drive API error при чтении папки: {e}") from e

        for item in response.get("files", []):
            files.append(
                DriveCsvFile(
                    file_id=item["id"],
                    name=item["name"],
                    modified_time=item.get("modifiedTime", ""),
                    size_bytes=int(item.get("size", 0) or 0),
                )
            )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return sorted(files, key=lambda item: item.name.lower())


def _download_csv_file(service, file_info: DriveCsvFile, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_info.file_id, supportsAllDrives=True)

    total_mb = file_info.size_bytes / (1024 * 1024) if file_info.size_bytes else 0
    logger.info("📥 Начинаем скачивание файла из Drive: %s (%.2f MB)", file_info.name, total_mb)

    with open(destination, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        last_logged_percent = -1
        while not done:
            try:
                status, done = downloader.next_chunk()
            except HttpError as e:
                raise PermissionError(f"Ошибка скачивания файла {file_info.name}: {e}") from e

            if status is not None:
                percent = int(status.progress() * 100)
                if percent >= last_logged_percent + 10 or percent == 100:
                    logger.info("📦 %s: %s%%", file_info.name, percent)
                    last_logged_percent = percent

    return destination


def check_drive_folder_access(*, folder_url_or_id: str, service_account_info: dict) -> DriveAccessReport:
    folder_id = extract_drive_folder_id(folder_url_or_id)
    logger.info("🔎 Проверка доступа к Google Drive папке: %s", folder_id)

    service = _build_drive_service(service_account_info)
    csv_files = _list_csv_files(service, folder_id)
    logger.info("✅ Доступ к папке Google Drive подтвержден. CSV файлов: %s", len(csv_files))

    return DriveAccessReport(folder_id=folder_id, csv_count=len(csv_files), can_access=True)


def sync_drive_folder_csvs(
    *,
    folder_url_or_id: str,
    service_account_info: dict,
    destination_dir: Path,
) -> list[Path]:
    report = check_drive_folder_access(
        folder_url_or_id=folder_url_or_id,
        service_account_info=service_account_info,
    )
    service = _build_drive_service(service_account_info)
    csv_files = _list_csv_files(service, report.folder_id)

    if not csv_files:
        logger.warning("⚠️ В папке Google Drive %s нет CSV-файлов", report.folder_id)
        return []

    downloaded_paths: list[Path] = []
    total_files = len(csv_files)
    for idx, file_info in enumerate(csv_files, start=1):
        safe_name = Path(file_info.name).name
        logger.info("➡️ Обработка файла %s/%s: %s", idx, total_files, safe_name)
        path = _download_csv_file(service, file_info, destination_dir / safe_name)
        downloaded_paths.append(path)
        logger.info("⬇️ Скачан CSV из Drive: %s (%s/%s)", path.name, idx, total_files)

    logger.info("✅ Синхронизация из Google Drive завершена. Файлов: %s", len(downloaded_paths))
    return downloaded_paths
