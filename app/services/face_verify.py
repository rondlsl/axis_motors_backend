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
    return verified, details


def _write_upload_to_temp_file(upload_file) -> str:
    """Сохраняет UploadFile/файлоподобный объект во временный файл и возвращает путь."""
    filename = getattr(upload_file, 'filename', 'upload') or 'upload'
    suffix = Path(filename).suffix
    if not suffix:
        suffix = '.jpg'  # Дефолтное расширение для изображений
    
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    
    # DEBUG: Логируем информацию о файле
    print(f"[UPLOAD_DEBUG] Filename: {filename}")
    print(f"[UPLOAD_DEBUG] Suffix: {suffix}")
    print(f"[UPLOAD_DEBUG] Upload file type: {type(upload_file)}")
    
    with tmp as f:
        src = getattr(upload_file, 'file', None) or upload_file
        print(f"[UPLOAD_DEBUG] Source type: {type(src)}")
        
        # Проверяем, что источник не пустой
        if hasattr(src, 'read'):
            # Читаем первые несколько байт для проверки
            try:
                initial_pos = src.tell() if hasattr(src, 'tell') else 0
                first_bytes = src.read(10) if hasattr(src, 'read') else b''
                print(f"[UPLOAD_DEBUG] First 10 bytes: {first_bytes}")
                
                # Возвращаем позицию в начало
                if hasattr(src, 'seek'):
                    src.seek(initial_pos)
                else:
                    # Если нет seek, создаем новый объект
                    src = getattr(upload_file, 'file', None) or upload_file
            except Exception as e:
                print(f"[UPLOAD_DEBUG] Error reading initial bytes: {e}")
        
        shutil.copyfileobj(src, f)
        print(f"[UPLOAD_DEBUG] Written to temp file: {tmp.name}")
    
    try:
        if hasattr(upload_file, 'file') and hasattr(upload_file.file, 'seek'):
            upload_file.file.seek(0)
    except Exception:
        pass
    
    # Проверяем размер созданного файла
    temp_path = Path(tmp.name)
    if temp_path.exists():
        size = temp_path.stat().st_size
        print(f"[UPLOAD_DEBUG] Temp file size: {size} bytes")
        if size == 0:
            print("[UPLOAD_DEBUG] WARNING: Temp file is empty!")
    else:
        print("[UPLOAD_DEBUG] ERROR: Temp file was not created!")
    
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

    selfie_tmp_path = _write_upload_to_temp_file(upload_file)
    
    # DEBUG: Проверяем, что файлы действительно существуют и имеют размер
    tmp_path_obj = Path(selfie_tmp_path)
    profile_path_obj = Path(resolved)
    
    print(f"[FILE_DEBUG] Temp file exists: {tmp_path_obj.exists()}, size: {tmp_path_obj.stat().st_size if tmp_path_obj.exists() else 'N/A'} bytes")
    print(f"[FILE_DEBUG] Profile file exists: {profile_path_obj.exists()}, size: {profile_path_obj.stat().st_size if profile_path_obj.exists() else 'N/A'} bytes")
    print(f"[FILE_DEBUG] Temp file path: {tmp_path_obj.absolute()}")
    print(f"[FILE_DEBUG] Profile file path: {profile_path_obj.absolute()}")
    
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
        
        # Копируем селфи из профиля
        profile_debug_path = debug_dir / f"profile_selfie_{timestamp}_{user.id}.jpg"
        shutil.copy2(str(resolved), profile_debug_path)
        debug_copies.append(str(profile_debug_path))
    
    try:
        # Проверка с ArcFace
        is_same, details = verify_faces(selfie_tmp_path, str(resolved))
        
        # DEBUG: Логируем результат для сравнения с вашим скриптом
        print(f"[FACE_VERIFY_DEBUG] Distance: {details['distance']:.6f}, Threshold: {details['threshold']:.6f}")
        print(f"[FACE_VERIFY_DEBUG] Verified: {is_same}")
        print(f"[FACE_VERIFY_DEBUG] Files: {selfie_tmp_path} vs {resolved}")
        
        if is_same:
            return True, "ok"
        
        return False, "Личность не подтверждена по селфи. Убедитесь, что на фото именно вы, и попробуйте снова."
    except Exception as e:
        print(f"[FACE_VERIFY_DEBUG] Exception: {e}")
        return False, f"Ошибка проверки селфи: {str(e)}"
    finally:
        # Очищаем временный файл
        try:
            import os
            if os.path.exists(selfie_tmp_path):
                os.unlink(selfie_tmp_path)
        except Exception:
            pass


