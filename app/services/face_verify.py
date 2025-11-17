from typing import Tuple, Dict, Any
from pathlib import Path
from tempfile import NamedTemporaryFile
import shutil


def verify_faces(img1_path: str, img2_path: str,
                 model: str = "ArcFace",
                 detector: str = "opencv",
                 enforce_detection: bool = False,
                 threshold: float = 0.68) -> Tuple[bool, Dict[str, Any]]:
    """
    Сравнивает два изображения лиц и возвращает (is_same, details).

    - is_same: True, если это один и тот же человек по модели
    - details: словарь с полями distance/threshold/model/detector
    
    ВНИМАНИЕ: Импорт DeepFace происходит только внутри функции для ленивой загрузки.
    """
    # Импортируем DeepFace только когда функция действительно вызывается
    # Это предотвращает загрузку TensorFlow при старте приложения
    try:
        from deepface import DeepFace
    except ImportError as e:
        raise Exception(f"DeepFace не установлен или не может быть загружен: {e}")

    res = DeepFace.verify(
        img1_path=img1_path,
        img2_path=img2_path,
        model_name=model,
        detector_backend=detector,
        enforce_detection=enforce_detection,
        threshold=threshold
    )

    details = {
        "distance": float(res.get("distance", 0.0)),
        "threshold": float(res.get("threshold", 0.0)),
        "model": model,
        "detector": detector,
    }
    
    verified = bool(res.get("verified", False))
    return verified, details


def _write_upload_to_temp_file(upload_file) -> str:
    """Сохраняет UploadFile/файлоподобный объект во временный файл и возвращает путь."""
    filename = getattr(upload_file, 'filename', 'upload') or 'upload'
    suffix = Path(filename).suffix
    if not suffix:
        suffix = '.jpg'  # Дефолтное расширение для изображений
    
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
    candidates = [Path(p), Path(".") / p.lstrip("/"), ]
    
    if p.startswith("uploads/"):
        candidates.extend([Path(p),Path(".") / p,])
    
    if p.startswith("/uploads/"):
        candidates.append(Path(".") / p.lstrip("/"))
    
    if "/" not in p:
        candidates.extend([Path("uploads/documents") / p, Path(".") / "uploads/documents" / p,])
    
    for c in candidates:
        if c and c.exists():
            return c
    return None


def verify_user_upload_against_profile(user, upload_file) -> Tuple[bool, str]:
    """
    Сравнивает selfie (upload_file) с селфи из профиля пользователя (selfie_url).
    Возвращает (is_same, message). При False message содержит причину для 400.
    
    Модель AI загружается лениво (при первом использовании) для экономии RAM при старте.
    """
    import os
    
    # Проверяем переменную окружения для отключения face verification (по умолчанию ВКЛЮЧЕНА)
    face_verify_enabled = os.getenv("ENABLE_FACE_VERIFICATION", "true").lower() == "true"
    
    if not face_verify_enabled:
        # Face verification отключена через .env - пропускаем проверку
        print("⚠️ Face verification отключена через ENABLE_FACE_VERIFICATION=false")
        return True, "ok"
    
    if not user or not getattr(user, 'selfie_url', None):
        return False, "В профиле отсутствует селфи для проверки личности"

    resolved = _resolve_profile_document_path(user.selfie_url)
    if not resolved:
        return False, "Файл селфи из профиля не найден для сверки личности"

    selfie_tmp_path = _write_upload_to_temp_file(upload_file)
    
    try:
        print(f"🔍 Проверка лица пользователя {getattr(user, 'id', 'unknown')}...")
        
        # Проверка с ArcFace (строгий threshold для высокой точности)
        # Модель загрузится только при первом вызове verify_faces
        is_same, details = verify_faces(
            selfie_tmp_path, 
            str(resolved), 
            threshold=0.40,
            enforce_detection=False
        )
        
        print(f"✅ Проверка лица завершена: is_same={is_same}, distance={details.get('distance')}")
        
        if is_same:
            return True, "ok"
        
        return False, "Ой! Похоже на фотографии не вы, но если это вы, то пожалуйста сделайте селфи как в профиле."
    except Exception as e:
        print(f"❌ Ошибка при проверке лица: {str(e)}")
        # При ошибке AI проверки НЕ блокируем пользователя (чтобы не ломать UX)
        # Но логируем для мониторинга
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return True, "ok"  # Пропускаем при ошибке AI
    finally:
        # Очищаем временный файл
        try:
            if os.path.exists(selfie_tmp_path):
                os.unlink(selfie_tmp_path)
        except Exception:
            pass


