from typing import Tuple, Dict, Any
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil


def verify_faces(img1_path: str, img2_path: str,
                 model: str = "ArcFace",
                 detector: str = "opencv",
                 enforce_detection: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """
    Сравнивает два изображения лиц и возвращает (is_same, details).

    - is_same: True, если это один и тот же человек по модели
    - details: словарь с полями distance/threshold/model/detector
    """
    from deepface import DeepFace

    res = DeepFace.verify(
        img1_path=img1_path,
        img2_path=img2_path,
        model_name=model,
        detector_backend=detector,
        enforce_detection=enforce_detection
    )

    details = {
        "distance": float(res.get("distance", 0.0)),
        "threshold": float(res.get("threshold", 0.0)),
        "model": model,
        "detector": detector,
    }
    return bool(res.get("verified", False)), details


def _write_upload_to_temp_file(upload_file) -> str:
    """Сохраняет UploadFile/файлоподобный объект во временный файл и возвращает путь."""
    filename = getattr(upload_file, 'filename', 'upload') or 'upload'
    suffix = Path(filename).suffix
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp as f:
        # FastAPI UploadFile имеет .file
        src = getattr(upload_file, 'file', None) or upload_file
        shutil.copyfileobj(src, f)
    try:
        if hasattr(upload_file, 'file') and hasattr(upload_file.file, 'seek'):
            upload_file.file.seek(0)
    except Exception:
        pass
    return tmp.name


def _resolve_profile_document_path(profile_doc_path: str) -> Path | None:
    """
    Пытается найти файл документа пользователя по разным вариантам путей.
    Возвращает Path если найден, иначе None.
    """
    if not profile_doc_path:
        return None
    p = profile_doc_path.strip()
    candidates = [
        Path(p),
        Path(".") / p.lstrip("/"),
        Path("uploads") / Path(p).name,
    ]
    if p.startswith("/uploads/"):
        candidates.append(Path(".") / p.lstrip("/"))
    if p.startswith("uploads/"):
        candidates.append(Path(p))
        candidates.append(Path(".") / p)
    for c in candidates:
        if c and c.exists():
            return c
    return None


def verify_user_upload_against_profile(user, upload_file) -> Tuple[bool, str]:
    """
    Сравнивает selfie (upload_file) с фото из профиля пользователя (id_card_front_url).
    Возвращает (is_same, message). При False message содержит причину для 400.
    """
    if not user or not getattr(user, 'id_card_front_url', None):
        return False, "В профиле отсутствует фото документа для проверки личности"

    resolved = _resolve_profile_document_path(user.id_card_front_url)
    if not resolved:
        return False, "Файл документа из профиля не найден для сверки личности"

    selfie_tmp_path = _write_upload_to_temp_file(upload_file)
    try:
        is_same, _details = verify_faces(selfie_tmp_path, str(resolved))
        if not is_same:
            return False, "Личность не подтверждена по селфи. Убедитесь, что на фото именно вы, и попробуйте снова."
        return True, "ok"
    except Exception as e:
        return False, f"Ошибка проверки селфи: {str(e)}"


