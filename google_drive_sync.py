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
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:  # pragma: no cover - handled by runtime checks
    service_account = None
    build = None
    MediaFileUpload = None
    MediaIoBaseDownload = None
    HttpError = Exception
    GOOGLE_DRIVE_AVAILABLE = False


DRIVE_SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_SCOPE_FULL = "https://www.googleapis.com/auth/drive"


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


@dataclass
class DriveUploadResult:
    file_id: str
    folder_id: str
    name: str
    size_bytes: int
    web_view_link: str
    web_content_link: str | None


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


def _build_drive_service(service_account_info: dict, *, scopes: list[str] | None = None):
    if not GOOGLE_DRIVE_AVAILABLE:
        raise ImportError(
            "Для синхронизации из Google Drive установите зависимости: "
            "google-api-python-client и google-auth"
        )

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes or [DRIVE_SCOPE_READONLY],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape_drive_query_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _find_existing_file_id(service, folder_id: str, file_name: str) -> str | None:
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        f"name = '{_escape_drive_query_value(file_name)}'"
    )
    response = service.files().list(
        q=query,
        pageSize=1,
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = response.get("files", [])
    if not files:
        return None
    return str(files[0]["id"])


def _build_drive_file_links(file_id: str, *, web_view_link: str | None, web_content_link: str | None) -> tuple[str, str | None]:
    resolved_view = web_view_link or f"https://drive.google.com/file/d/{file_id}/view?usp=drive_link"
    resolved_content = web_content_link or f"https://drive.google.com/uc?id={file_id}&export=download"
    return resolved_view, resolved_content


def _guess_drive_mime_type(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix == ".xls":
        return "application/vnd.ms-excel"
    return "application/octet-stream"


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


def upload_file_to_drive(
    *,
    source_path: Path,
    folder_url_or_id: str,
    service_account_info: dict,
    target_name: str | None = None,
) -> DriveUploadResult:
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Не найден файл для выгрузки в Google Drive: {source_path}")

    folder_id = extract_drive_folder_id(folder_url_or_id)
    service = _build_drive_service(service_account_info, scopes=[DRIVE_SCOPE_FULL])
    upload_name = Path(target_name).name if target_name else source_path.name
    file_size_bytes = source_path.stat().st_size
    logger.info(
        "☁️ Google Drive upload start: source=%s folder=%s name=%s size_mb=%.2f",
        source_path,
        folder_id,
        upload_name,
        file_size_bytes / (1024 * 1024),
    )

    existing_file_id = _find_existing_file_id(service, folder_id, upload_name)
    media = MediaFileUpload(
        str(source_path),
        mimetype=_guess_drive_mime_type(source_path),
        resumable=True,
        chunksize=8 * 1024 * 1024,
    )
    fields = "id, name, size, webViewLink, webContentLink"

    if existing_file_id:
        logger.info(
            "♻️ Google Drive upload will update existing file: folder=%s file_id=%s name=%s",
            folder_id,
            existing_file_id,
            upload_name,
        )
        request = service.files().update(
            fileId=existing_file_id,
            body={"name": upload_name},
            media_body=media,
            fields=fields,
            supportsAllDrives=True,
        )
    else:
        request = service.files().create(
            body={"name": upload_name, "parents": [folder_id]},
            media_body=media,
            fields=fields,
            supportsAllDrives=True,
        )

    response = None
    last_logged_percent = -1
    while response is None:
        try:
            status, response = request.next_chunk()
        except HttpError as e:
            raise PermissionError(f"Ошибка загрузки файла {upload_name} в Google Drive: {e}") from e

        if status is not None:
            percent = int(status.progress() * 100)
            if percent >= last_logged_percent + 10 or percent == 100:
                logger.info("☁️ Upload progress %s: %s%%", upload_name, percent)
                last_logged_percent = percent

    file_id = str(response["id"])
    web_view_link, web_content_link = _build_drive_file_links(
        file_id,
        web_view_link=response.get("webViewLink"),
        web_content_link=response.get("webContentLink"),
    )
    uploaded_size = int(response.get("size", file_size_bytes) or file_size_bytes)
    logger.info(
        "✅ Google Drive upload complete: file_id=%s name=%s size_bytes=%s view_link=%s",
        file_id,
        response.get("name", upload_name),
        uploaded_size,
        web_view_link,
    )

    return DriveUploadResult(
        file_id=file_id,
        folder_id=folder_id,
        name=str(response.get("name", upload_name)),
        size_bytes=uploaded_size,
        web_view_link=web_view_link,
        web_content_link=web_content_link,
    )


def _prune_orphan_destination_csvs(destination_dir: Path, keep_paths: list[Path]) -> list[Path]:
    destination_dir = Path(destination_dir)
    if not destination_dir.exists():
        return []

    keep_resolved = {path.resolve() for path in keep_paths}
    removed: list[Path] = []
    for candidate in destination_dir.glob("*.csv"):
        try:
            if candidate.resolve() in keep_resolved:
                continue
        except FileNotFoundError:
            continue
        if candidate.is_file():
            candidate.unlink()
            removed.append(candidate)
    return removed


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

    removed_paths = _prune_orphan_destination_csvs(destination_dir, downloaded_paths)
    if removed_paths:
        logger.info("🧹 Удалены устаревшие raw-файлы после sync: %s", len(removed_paths))

    logger.info("✅ Синхронизация из Google Drive завершена. Файлов: %s", len(downloaded_paths))
    return downloaded_paths
