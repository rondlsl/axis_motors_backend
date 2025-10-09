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
    
    for i, c in enumerate(candidates):
        if c and c.exists():
            print(f"✓ Found profile document at: {c.absolute()}")
            print(f"✓ Profile document size: {c.stat().st_size} bytes")
            return c
        else:
            print(f"✗ Not found ({i+1}/{len(candidates)}): {c}")
    
    print(f"❌ Profile document not found. Tried {len(candidates)} paths")
    return None


def verify_user_upload_against_profile(user, upload_file, save_debug_copies: bool = True) -> Tuple[bool, str]:
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
    print(f"Profile selfie full path: {resolved.absolute()}")
    
    selfie_tmp_path = _write_upload_to_temp_file(upload_file)
    print(f"New rental selfie temp path: {selfie_tmp_path}")
    print(f"New rental selfie absolute path: {Path(selfie_tmp_path).absolute()}")
    
    # Информация о новом селфи
    new_selfie_path = Path(selfie_tmp_path)
    if new_selfie_path.exists():
        print(f"New rental selfie size: {new_selfie_path.stat().st_size} bytes")
    
    # Информация о селфи из профиля
    if resolved.exists():
        print(f"Profile selfie size: {resolved.stat().st_size} bytes")
    
    # Сохраняем копии для отладки (если включено)
    debug_copies = []
    if save_debug_copies:
        import shutil
        from datetime import datetime
        
        debug_dir = Path("debug_face_verification")
        debug_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Копируем новое селфи
        new_debug_path = debug_dir / f"rental_selfie_{timestamp}_{user.id}.jpg"
        shutil.copy2(selfie_tmp_path, new_debug_path)
        debug_copies.append(str(new_debug_path))
        print(f"🔍 Debug copy saved: {new_debug_path.absolute()}")
        
        # Копируем селфи из профиля
        profile_debug_path = debug_dir / f"profile_selfie_{timestamp}_{user.id}.jpg"
        shutil.copy2(str(resolved), profile_debug_path)
        debug_copies.append(str(profile_debug_path))
        print(f"🔍 Debug copy saved: {profile_debug_path.absolute()}")
    
    try:
        # Первая попытка с ArcFace (основная модель)
        print(f"Starting face verification: {selfie_tmp_path} vs {resolved}")
        is_same, details = verify_faces(selfie_tmp_path, str(resolved))
        print(f"Face verification result (ArcFace): {is_same}, details: {details}")
        
        if is_same:
            return True, "ok"
        
        # Если ArcFace не прошел, пробуем с VGG-Face (более мягкая модель)
        print("ArcFace failed, trying VGG-Face...")
        is_same_vgg, details_vgg = verify_faces(selfie_tmp_path, str(resolved), model="VGG-Face")
        print(f"Face verification result (VGG-Face): {is_same_vgg}, details: {details_vgg}")
        
        if is_same_vgg:
            return True, "ok"
        
        return False, "Личность не подтверждена по селфи. Убедитесь, что на фото именно вы, и попробуйте снова."
    except Exception as e:
        print(f"Error in face verification: {e}")
        return False, f"Ошибка проверки селфи: {str(e)}"
    finally:
        # Очищаем временный файл
        try:
            import os
            if os.path.exists(selfie_tmp_path):
                os.unlink(selfie_tmp_path)
                print(f"🧹 Cleaned up temp file: {selfie_tmp_path}")
        except Exception:
            pass


