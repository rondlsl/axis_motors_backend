from typing import Tuple, Dict, Any
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil


def verify_faces(img1_path: str, img2_path: str,
                 model: str = "Facenet",
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
    
    verified = bool(res.get("verified", False))
    print(f"DeepFace verification: {verified}, distance: {details['distance']:.4f}, threshold: {details['threshold']:.4f}")
    
    return verified, details


def _write_upload_to_temp_file(upload_file) -> str:
    """Сохраняет UploadFile/файлоподобный объект во временный файл и возвращает путь."""
    filename = getattr(upload_file, 'filename', 'upload') or 'upload'
    suffix = Path(filename).suffix
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp as f:
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
    print(f"Looking for profile document: {p}")
    
    candidates = [Path(p), Path(".") / p.lstrip("/"), ]
    
    if p.startswith("uploads/"):
        candidates.extend([Path(p),Path(".") / p,])
    
    if p.startswith("/uploads/"):
        candidates.append(Path(".") / p.lstrip("/"))
    
    if "/" not in p:
        candidates.extend([Path("uploads/documents") / p, Path(".") / "uploads/documents" / p,])
    
    for c in candidates:
        if c and c.exists():
            print(f"Found profile document at: {c.absolute()}")
            return c
        else:
            print(f"Not found: {c}")
    
    print(f"Profile document not found. Tried {len(candidates)} paths")
    return None


def verify_user_upload_against_profile(user, upload_file) -> Tuple[bool, str]:
    """
    Сравнивает selfie (upload_file) с селфи из профиля пользователя (selfie_url).
    Возвращает (is_same, message). При False message содержит причину для 400.
    """
    if not user or not getattr(user, 'selfie_url', None):
        return False, "В профиле отсутствует селфи для проверки личности"

    resolved = _resolve_profile_document_path(user.selfie_url)
    if not resolved:
        return False, "Файл селфи из профиля не найден для сверки личности"

    print(f"Comparing new selfie with profile selfie: {resolved}")
    
    selfie_tmp_path = _write_upload_to_temp_file(upload_file)
    try:
        # Первая попытка с Facenet (основная модель)
        is_same, details = verify_faces(selfie_tmp_path, str(resolved))
        print(f"Face verification result (Facenet): {is_same}, details: {details}")
        
        if is_same:
            return True, "ok"
        
        # Если Facenet не прошел, пробуем с VGG-Face (более мягкая модель)
        print("Facenet failed, trying VGG-Face...")
        is_same_vgg, details_vgg = verify_faces(selfie_tmp_path, str(resolved), model="VGG-Face")
        print(f"Face verification result (VGG-Face): {is_same_vgg}, details: {details_vgg}")
        
        if is_same_vgg:
            return True, "ok"
        
        return False, "Личность не подтверждена по селфи. Убедитесь, что на фото именно вы, и попробуйте снова."
    except Exception as e:
        print(f"Error in face verification: {e}")
        return False, f"Ошибка проверки селфи: {str(e)}"


