#!/usr/bin/env python3
"""
Оптимизированный скрипт для конвертации изображений в MinIO в формат WebP.
Поддерживает параллельную обработку, чекпоинты и прогресс-бар.

Запуск:
    python scripts/convert_images_to_webp.py --dry-run
    python scripts/convert_images_to_webp.py --workers 8
    python scripts/convert_images_to_webp.py --resume

Опции:
    --dry-run       Показать что будет конвертировано, без реальных изменений
    --delete-old    Удалить оригинальные файлы после конвертации
    --table TABLE   Обработать только указанную таблицу
    --workers N     Количество параллельных воркеров (по умолчанию 4)
    --resume        Продолжить с последнего чекпоинта
    --batch-size N  Размер батча для коммита в БД (по умолчанию 100)
"""
import os
import sys
import argparse
import logging
import json
import pickle
from io import BytesIO
from typing import List, Tuple, Optional, Dict
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import time

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Попробуем импортировать tqdm для прогресс-бара
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("⚠️  tqdm не установлен. Установите: pip install tqdm")

# Импорт конфигурации
from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET_UPLOADS,
    MINIO_PUBLIC_URL,
)

# Пробуем получить DATABASE_URL из разных источников
try:
    from app.core.config import DATABASE_URL
except Exception:
    DATABASE_URL = None

# Если DATABASE_URL не загрузился, пробуем собрать вручную
if not DATABASE_URL or 'None' in str(DATABASE_URL):
    from app.core.config import (
        POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
    )
    # Проверяем что все переменные есть
    if all([POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB]):
        DATABASE_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    else:
        # Дефолтные значения для локальной разработки
        DATABASE_URL = os.getenv(
            'DATABASE_URL',
            'postgresql+psycopg2://postgres:postgres@localhost:5432/azv_motors_backend_v2'
        )

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
WEBP_QUALITY = 85
CHECKPOINT_FILE = Path(__file__).parent / '.webp_migration_checkpoint.pkl'


@dataclass
class MigrationStats:
    """Статистика миграции"""
    total_urls: int = 0
    processed: int = 0
    converted: int = 0
    already_exists: int = 0
    not_found: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    db_updated: int = 0
    skipped: int = 0


@dataclass
class ConversionResult:
    """Результат конвертации одного файла"""
    url: str
    status: str  # converted, exists, not_found, error, skipped
    original_size: int = 0
    new_size: int = 0
    new_url: str = ""
    error_msg: str = ""


def get_s3_client():
    """Создать клиент S3/MinIO с оптимизированными настройками"""
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            max_pool_connections=50,  # Больше соединений для параллельной работы
            retries={'max_attempts': 3}
        )
    )


def get_db_engine():
    """Создать engine БД"""
    return create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True
    )


def is_convertible_image(path: str) -> bool:
    """Проверить, можно ли конвертировать файл по пути"""
    if not path:
        return False
    # Уже WebP - пропускаем
    if path.lower().endswith('.webp'):
        return False
    ext = os.path.splitext(path.lower())[1]
    return ext in IMAGE_EXTENSIONS


def parse_db_path(db_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Извлечь bucket и key из пути/URL в БД.
    
    Форматы в БД:
    - uploads/documents/uuid.jpg -> bucket=uploads, key=documents/uuid.jpg
    - /uploads/cars/X60/front.jpg -> bucket=uploads, key=cars/X60/front.jpg
    - https://msmain.azvmotors.kz/uploads/documents/uuid.jpg -> bucket=uploads, key=documents/uuid.jpg
    
    Returns: (bucket, key) или (None, None)
    """
    if not db_path:
        return None, None
    
    try:
        path = db_path
        
        # Если это полный URL - извлекаем путь
        if path.startswith('http://') or path.startswith('https://'):
            # https://msmain.azvmotors.kz/uploads/documents/uuid.jpg
            # Убираем протокол и домен
            path = path.split('://', 1)[1]  # msmain.azvmotors.kz/uploads/documents/uuid.jpg
            path = path.split('/', 1)[1] if '/' in path else ''  # uploads/documents/uuid.jpg
        
        # Убираем начальный слеш если есть
        path = path.lstrip('/')
        
        if not path:
            return None, None
        
        # Разделяем на bucket и key
        parts = path.split('/', 1)
        
        if len(parts) < 2:
            return None, None
        
        bucket = parts[0]  # uploads
        key = parts[1]     # documents/uuid.jpg или cars/X60/front.jpg
        
        return bucket, key
    except Exception:
        return None, None


def convert_image_to_webp(content: bytes) -> Tuple[Optional[bytes], int, int]:
    """Конвертировать изображение в WebP"""
    try:
        original_size = len(content)
        img = Image.open(BytesIO(content))
        
        # Конвертируем цветовое пространство
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        output = BytesIO()
        img.save(output, format='WEBP', quality=WEBP_QUALITY, method=4)  # method=4 быстрее чем 6
        output.seek(0)
        
        webp_content = output.getvalue()
        return webp_content, original_size, len(webp_content)
        
    except Exception as e:
        logger.debug(f"Ошибка конвертации: {e}")
        return None, 0, 0


def get_webp_path(original_path: str) -> str:
    """
    Получить путь/URL для WebP версии файла (для БД).
    Сохраняет исходный формат (URL остаётся URL, путь остаётся путём).
    """
    base, _ = os.path.splitext(original_path)
    return f"{base}.webp"


def get_webp_key(original_key: str) -> str:
    """Получить key для WebP версии файла (для MinIO)"""
    base, _ = os.path.splitext(original_key)
    return f"{base}.webp"


# ============================================================
# СБОР URL ИЗ БАЗЫ ДАННЫХ (оптимизированный)
# ============================================================

def collect_all_urls_fast(engine, tables: Optional[List[str]] = None) -> Dict[str, List[dict]]:
    """
    Быстрый сбор всех URL из БД одним проходом.
    Возвращает Dict[url, List[{table, column, id, ...}]]
    """
    all_urls = {}
    
    with engine.connect() as conn:
        # Users - простые поля
        if not tables or 'users' in tables:
            logger.info("Сканирование users...")
            user_columns = [
                'selfie_with_license_url', 'selfie_url', 'drivers_license_url',
                'id_card_front_url', 'id_card_back_url',
                'psych_neurology_certificate_url', 'narcology_certificate_url',
                'pension_contributions_certificate_url'
            ]
            
            for col in user_columns:
                result = conn.execute(text(
                    f"SELECT id, {col} FROM users WHERE {col} IS NOT NULL AND {col} != '' AND {col} NOT LIKE '%.webp'"
                ))
                for row in result.fetchall():
                    url = row[1]
                    if url and is_convertible_image(url):
                        if url not in all_urls:
                            all_urls[url] = []
                        all_urls[url].append({
                            'table': 'users', 'column': col,
                            'id': str(row[0]), 'id_column': 'id'
                        })
            
            logger.info(f"  users: найдено {sum(1 for u in all_urls.values() if any(x['table']=='users' for x in u))} URL")
        
        # Cars - JSON поле photos
        if not tables or 'cars' in tables:
            logger.info("Сканирование cars...")
            result = conn.execute(text(
                "SELECT id, photos FROM cars WHERE photos IS NOT NULL"
            ))
            
            cars_count = 0
            for row in result.fetchall():
                car_id, photos = row
                if not photos:
                    continue
                
                try:
                    photos_list = json.loads(photos) if isinstance(photos, str) else (photos or [])
                except Exception:
                    continue
                
                for idx, url in enumerate(photos_list):
                    if url and is_convertible_image(url):
                        if url not in all_urls:
                            all_urls[url] = []
                        all_urls[url].append({
                            'table': 'cars', 'column': 'photos',
                            'id': str(car_id), 'id_column': 'id',
                            'array_index': idx, 'is_json': True
                        })
                        cars_count += 1
            
            logger.info(f"  cars: найдено {cars_count} URL")
        
        # Rental history - ARRAY поля
        if not tables or 'rental_history' in tables:
            logger.info("Сканирование rental_history...")
            rental_columns = [
                'photos_before', 'photos_after',
                'delivery_photos_before', 'delivery_photos_after',
                'mechanic_photos_before', 'mechanic_photos_after'
            ]
            
            rental_count = 0
            for col in rental_columns:
                try:
                    result = conn.execute(text(
                        f"SELECT id, {col} FROM rental_history WHERE {col} IS NOT NULL AND array_length({col}, 1) > 0"
                    ))
                    
                    for row in result.fetchall():
                        rental_id, photos = row
                        if not photos:
                            continue
                        
                        for idx, url in enumerate(photos):
                            if url and is_convertible_image(url):
                                if url not in all_urls:
                                    all_urls[url] = []
                                all_urls[url].append({
                                    'table': 'rental_history', 'column': col,
                                    'id': str(rental_id), 'id_column': 'id',
                                    'array_index': idx, 'is_array': True
                                })
                                rental_count += 1
                except Exception as e:
                    logger.debug(f"  Ошибка {col}: {e}")
            
            logger.info(f"  rental_history: найдено {rental_count} URL")
        
        # Support messages
        if not tables or 'support_messages' in tables:
            logger.info("Сканирование support_messages...")
            try:
                result = conn.execute(text(
                    "SELECT id, media_url FROM support_messages WHERE media_url IS NOT NULL AND media_url != '' AND media_url NOT LIKE '%.webp'"
                ))
                
                support_count = 0
                for row in result.fetchall():
                    url = row[1]
                    if url and is_convertible_image(url):
                        if url not in all_urls:
                            all_urls[url] = []
                        all_urls[url].append({
                            'table': 'support_messages', 'column': 'media_url',
                            'id': str(row[0]), 'id_column': 'id'
                        })
                        support_count += 1
                
                logger.info(f"  support_messages: найдено {support_count} URL")
            except Exception as e:
                logger.debug(f"  support_messages: {e}")
        
        # Contract files
        if not tables or 'contract_files' in tables:
            logger.info("Сканирование contract_files...")
            try:
                result = conn.execute(text(
                    "SELECT id, file_url FROM contract_files WHERE file_url IS NOT NULL AND file_url != '' AND file_url NOT LIKE '%.webp'"
                ))
                
                contract_count = 0
                for row in result.fetchall():
                    url = row[1]
                    if url and is_convertible_image(url):
                        if url not in all_urls:
                            all_urls[url] = []
                        all_urls[url].append({
                            'table': 'contract_files', 'column': 'file_url',
                            'id': str(row[0]), 'id_column': 'id'
                        })
                        contract_count += 1
                
                logger.info(f"  contract_files: найдено {contract_count} URL")
            except Exception as e:
                logger.debug(f"  contract_files: {e}")
    
    return all_urls


# ============================================================
# КОНВЕРТАЦИЯ (параллельная)
# ============================================================

def convert_single_file(args: tuple) -> ConversionResult:
    """
    Конвертировать один файл (для параллельной обработки).
    args: (db_path, dry_run, delete_old)
    
    db_path - путь как хранится в БД: uploads/documents/uuid.jpg или /uploads/cars/X60/front.jpg
    """
    db_path, dry_run, delete_old = args
    
    # Каждый поток создаёт свой клиент
    s3_client = get_s3_client()
    
    # Парсим путь из БД
    bucket, key = parse_db_path(db_path)
    if not bucket or not key:
        return ConversionResult(url=db_path, status='error', error_msg='Invalid path format')
    
    new_key = get_webp_key(key)
    new_db_path = get_webp_path(db_path)  # Новый путь для БД
    
    # Проверяем существование WebP в MinIO
    try:
        s3_client.head_object(Bucket=bucket, Key=new_key)
        return ConversionResult(url=db_path, status='exists', new_url=new_db_path)
    except ClientError:
        pass
    
    if dry_run:
        return ConversionResult(url=db_path, status='would_convert', new_url=new_db_path)
    
    # Скачиваем оригинал из MinIO
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
    except ClientError:
        return ConversionResult(url=db_path, status='not_found', error_msg=f'File not found: {bucket}/{key}')
    except Exception as e:
        return ConversionResult(url=db_path, status='error', error_msg=str(e))
    
    # Конвертируем в WebP
    webp_content, original_size, new_size = convert_image_to_webp(content)
    
    if webp_content is None:
        return ConversionResult(url=db_path, status='error', error_msg='Conversion failed')
    
    # Загружаем WebP в MinIO
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=new_key,
            Body=BytesIO(webp_content),
            ContentType='image/webp',
            ContentLength=new_size
        )
    except Exception as e:
        return ConversionResult(url=db_path, status='error', error_msg=f'Upload failed: {e}')
    
    # Удаляем оригинал если нужно
    if delete_old:
        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass
    
    return ConversionResult(
        url=db_path, status='converted',
        original_size=original_size, new_size=new_size,
        new_url=new_db_path
    )


# ============================================================
# ОБНОВЛЕНИЕ БД (батчевое)
# ============================================================

def update_db_batch(engine, updates: List[tuple], dry_run: bool = False) -> int:
    """
    Батчевое обновление БД с отдельными транзакциями для каждого обновления.
    updates: List[(old_url, new_url, usages)]
    """
    if dry_run or not updates:
        return 0
    
    updated = 0
    
    for old_url, new_url, usages in updates:
        for usage in usages:
            table = usage['table']
            column = usage['column']
            record_id = usage['id']
            id_column = usage.get('id_column', 'id')
            
            # Каждое обновление в отдельной транзакции
            try:
                with engine.begin() as conn:
                    if usage.get('is_json'):
                        # JSON поле
                        result = conn.execute(
                            text(f"SELECT {column} FROM {table} WHERE {id_column} = :id"),
                            {"id": record_id}
                        )
                        row = result.fetchone()
                        if row and row[0]:
                            photos = row[0] if isinstance(row[0], list) else json.loads(row[0])
                            new_photos = [new_url if p == old_url else p for p in photos]
                            conn.execute(
                                text(f"UPDATE {table} SET {column} = :photos WHERE {id_column} = :id"),
                                {"photos": json.dumps(new_photos), "id": record_id}
                            )
                            updated += 1
                    
                    elif usage.get('is_array'):
                        # PostgreSQL ARRAY
                        result = conn.execute(
                            text(f"SELECT {column} FROM {table} WHERE {id_column} = :id"),
                            {"id": record_id}
                        )
                        row = result.fetchone()
                        if row and row[0]:
                            photos = list(row[0])
                            new_photos = [new_url if p == old_url else p for p in photos]
                            array_str = "{" + ",".join([f'"{u}"' for u in new_photos]) + "}"
                            conn.execute(
                                text(f"UPDATE {table} SET {column} = :photos WHERE {id_column} = :id"),
                                {"photos": array_str, "id": record_id}
                            )
                            updated += 1
                    
                    else:
                        # Простое поле
                        conn.execute(
                            text(f"UPDATE {table} SET {column} = :new_url WHERE {id_column} = :id AND {column} = :old_url"),
                            {"new_url": new_url, "id": record_id, "old_url": old_url}
                        )
                        updated += 1
            
            except Exception as e:
                logger.error(f"Ошибка обновления {table}.{column} id={record_id}: {e}")
    
    return updated


# ============================================================
# ЧЕКПОИНТЫ
# ============================================================

def save_checkpoint(processed_urls: set, stats: MigrationStats):
    """Сохранить чекпоинт"""
    try:
        with open(CHECKPOINT_FILE, 'wb') as f:
            pickle.dump({
                'processed_urls': processed_urls,
                'stats': stats
            }, f)
    except Exception as e:
        logger.warning(f"Не удалось сохранить чекпоинт: {e}")


def load_checkpoint() -> Tuple[set, Optional[MigrationStats]]:
    """Загрузить чекпоинт"""
    try:
        if CHECKPOINT_FILE.exists():
            with open(CHECKPOINT_FILE, 'rb') as f:
                data = pickle.load(f)
                return data.get('processed_urls', set()), data.get('stats')
    except Exception as e:
        logger.warning(f"Не удалось загрузить чекпоинт: {e}")
    return set(), None


def clear_checkpoint():
    """Удалить чекпоинт"""
    try:
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Оптимизированная конвертация изображений в WebP'
    )
    parser.add_argument('--dry-run', action='store_true', help='Без реальных изменений')
    parser.add_argument('--delete-old', action='store_true', help='Удалить оригиналы')
    parser.add_argument('--table', type=str, help='Только указанная таблица')
    parser.add_argument('--workers', type=int, default=4, help='Количество воркеров (default: 4)')
    parser.add_argument('--resume', action='store_true', help='Продолжить с чекпоинта')
    parser.add_argument('--batch-size', type=int, default=100, help='Размер батча для БД (default: 100)')
    parser.add_argument('--clear-checkpoint', action='store_true', help='Очистить чекпоинт и начать заново')
    
    args = parser.parse_args()
    tables = [args.table] if args.table else None
    
    # Очистка чекпоинта
    if args.clear_checkpoint:
        clear_checkpoint()
        logger.info("Чекпоинт очищен")
    
    logger.info("=" * 70)
    logger.info("ОПТИМИЗИРОВАННАЯ КОНВЕРТАЦИЯ ИЗОБРАЖЕНИЙ В WEBP")
    logger.info("=" * 70)
    logger.info(f"Воркеров: {args.workers}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Dry-run: {args.dry_run}")
    logger.info(f"Delete old: {args.delete_old}")
    logger.info(f"Resume: {args.resume}")
    logger.info(f"DATABASE_URL: {DATABASE_URL[:50]}...")
    logger.info("=" * 70)
    
    if args.delete_old and not args.dry_run:
        confirm = input("⚠️  ВНИМАНИЕ: Оригиналы будут удалены! Продолжить? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("Отменено")
            return
    
    # Загружаем чекпоинт
    processed_urls, saved_stats = set(), None
    if args.resume:
        processed_urls, saved_stats = load_checkpoint()
        if processed_urls:
            logger.info(f"Загружен чекпоинт: {len(processed_urls)} уже обработано")
    
    stats = saved_stats or MigrationStats()
    
    # Подключение к БД
    logger.info("\nПодключение к БД...")
    try:
        engine = get_db_engine()
        # Тест подключения
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ БД подключена")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        return
    
    # Сбор URL
    logger.info("\n" + "=" * 70)
    logger.info("ШАГ 1: СБОР URL ИЗ БД")
    logger.info("=" * 70)
    
    all_urls = collect_all_urls_fast(engine, tables)
    
    # Фильтруем уже обработанные
    if processed_urls:
        all_urls = {u: v for u, v in all_urls.items() if u not in processed_urls}
    
    stats.total_urls = len(all_urls) + len(processed_urls)
    logger.info(f"\nВсего URL: {stats.total_urls}")
    logger.info(f"К обработке: {len(all_urls)}")
    logger.info(f"Уже обработано: {len(processed_urls)}")
    
    if not all_urls:
        logger.info("Нет изображений для конвертации")
        clear_checkpoint()
        return
    
    # Конвертация
    logger.info("\n" + "=" * 70)
    logger.info("ШАГ 2: КОНВЕРТАЦИЯ ФАЙЛОВ")
    logger.info("=" * 70)
    
    url_list = list(all_urls.keys())
    db_updates = []  # (old_url, new_url, usages)
    
    start_time = time.time()
    
    # Подготовка аргументов для воркеров
    tasks = [(url, args.dry_run, args.delete_old) for url in url_list]
    
    # Прогресс-бар
    if HAS_TQDM:
        pbar = tqdm(total=len(tasks), desc="Конвертация", unit="файл")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(convert_single_file, task): task[0] for task in tasks}
        
        for future in as_completed(futures):
            url = futures[future]
            
            try:
                result = future.result()
                
                if result.status == 'converted':
                    stats.converted += 1
                    stats.bytes_before += result.original_size
                    stats.bytes_after += result.new_size
                    db_updates.append((url, result.new_url, all_urls[url]))
                elif result.status == 'exists':
                    stats.already_exists += 1
                    db_updates.append((url, result.new_url, all_urls[url]))
                elif result.status == 'would_convert':
                    stats.converted += 1
                elif result.status == 'not_found':
                    stats.not_found += 1
                elif result.status == 'error':
                    stats.errors += 1
                    logger.debug(f"Ошибка {url}: {result.error_msg}")
                
                processed_urls.add(url)
                stats.processed += 1
                
            except Exception as e:
                stats.errors += 1
                logger.error(f"Ошибка обработки {url}: {e}")
            
            # Обновляем прогресс
            if HAS_TQDM:
                pbar.update(1)
                elapsed = time.time() - start_time
                if stats.processed > 0:
                    rate = stats.processed / elapsed
                    eta = (len(tasks) - stats.processed) / rate if rate > 0 else 0
                    pbar.set_postfix({
                        'conv': stats.converted,
                        'err': stats.errors,
                        'ETA': f'{eta/60:.1f}m'
                    })
            
            # Батчевое обновление БД и сохранение чекпоинта
            if len(db_updates) >= args.batch_size:
                stats.db_updated += update_db_batch(engine, db_updates, args.dry_run)
                db_updates = []
                save_checkpoint(processed_urls, stats)
    
    if HAS_TQDM:
        pbar.close()
    
    # Финальное обновление БД
    if db_updates:
        logger.info("\nФинальное обновление БД...")
        stats.db_updated += update_db_batch(engine, db_updates, args.dry_run)
    
    # Очищаем чекпоинт при успешном завершении
    clear_checkpoint()
    
    # Итоги
    elapsed = time.time() - start_time
    
    logger.info("\n" + "=" * 70)
    logger.info("РЕЗУЛЬТАТЫ")
    logger.info("=" * 70)
    logger.info(f"Время: {elapsed/60:.1f} минут ({elapsed:.0f} сек)")
    logger.info(f"Скорость: {stats.processed/elapsed:.1f} файлов/сек")
    logger.info(f"Всего URL: {stats.total_urls}")
    logger.info(f"Обработано: {stats.processed}")
    logger.info(f"Конвертировано: {stats.converted}")
    logger.info(f"Уже в WebP: {stats.already_exists}")
    logger.info(f"Не найдено: {stats.not_found}")
    logger.info(f"Ошибок: {stats.errors}")
    logger.info(f"Обновлено в БД: {stats.db_updated}")
    
    if stats.bytes_before > 0:
        savings = stats.bytes_before - stats.bytes_after
        savings_pct = (savings / stats.bytes_before) * 100
        logger.info(f"\nРазмер до: {stats.bytes_before/1024/1024:.1f} MB")
        logger.info(f"Размер после: {stats.bytes_after/1024/1024:.1f} MB")
        logger.info(f"Экономия: {savings/1024/1024:.1f} MB ({savings_pct:.1f}%)")
    
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
