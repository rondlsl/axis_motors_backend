#!/usr/bin/env python3
"""
Скрипт для конвертации существующих изображений в MinIO в формат WebP.
Логика: сначала берём URL из БД, потом конвертируем файлы в MinIO.

Запуск:
    python scripts/convert_images_to_webp.py

Опции:
    --dry-run       Показать что будет конвертировано, без реальных изменений
    --delete-old    Удалить оригинальные файлы после конвертации
    --table TABLE   Обработать только указанную таблицу
"""
import os
import sys
import argparse
import logging
import json
from io import BytesIO
from typing import List, Tuple, Optional, Dict, Set
from urllib.parse import urlparse

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET_UPLOADS,
    MINIO_PUBLIC_URL,
    DATABASE_URL,
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Расширения изображений для конвертации
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}

# Качество WebP (0-100)
WEBP_QUALITY = 85


def get_s3_client():
    """Создать клиент S3/MinIO"""
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=boto3.session.Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'}
        )
    )


def get_db_session():
    """Создать сессию БД"""
    engine = create_engine(DATABASE_URL)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def is_convertible_image(url: str) -> bool:
    """Проверить, можно ли конвертировать файл по URL"""
    if not url:
        return False
    ext = os.path.splitext(urlparse(url).path.lower())[1]
    return ext in IMAGE_EXTENSIONS


def parse_minio_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Извлечь bucket и key из MinIO URL.
    
    URL формат: https://msmain.azvmotors.kz/uploads/folder/file.jpg
    Returns: (bucket, key) или (None, None)
    """
    if not url:
        return None, None
    
    try:
        # Убираем протокол
        url_without_protocol = url.replace("https://", "").replace("http://", "")
        parts = url_without_protocol.split("/", 1)
        
        if len(parts) < 2:
            return None, None
        
        path = parts[1]  # uploads/folder/file.jpg
        path_parts = path.split("/", 1)
        
        if len(path_parts) < 2:
            return None, None
        
        bucket = path_parts[0]
        key = path_parts[1]
        return bucket, key
    except Exception:
        return None, None


def convert_image_to_webp(content: bytes) -> Tuple[Optional[bytes], int, int]:
    """
    Конвертировать изображение в WebP.
    
    Returns: (webp_bytes, original_size, new_size) или (None, 0, 0) при ошибке
    """
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
        
        # Сохраняем в WebP
        output = BytesIO()
        img.save(output, format='WEBP', quality=WEBP_QUALITY, method=6)
        output.seek(0)
        
        webp_content = output.getvalue()
        return webp_content, original_size, len(webp_content)
        
    except Exception as e:
        logger.error(f"Ошибка конвертации: {e}")
        return None, 0, 0


def get_webp_url(original_url: str) -> str:
    """Получить URL для WebP версии файла"""
    base, _ = os.path.splitext(original_url)
    return f"{base}.webp"


def get_webp_key(original_key: str) -> str:
    """Получить key для WebP версии файла"""
    base, _ = os.path.splitext(original_key)
    return f"{base}.webp"


# ============================================================
# СБОР URL ИЗ БАЗЫ ДАННЫХ
# ============================================================

def collect_urls_from_users(db_session) -> Dict[str, List[dict]]:
    """Собрать URL изображений из таблицы users"""
    columns = [
        'selfie_with_license_url',
        'selfie_url',
        'drivers_license_url',
        'id_card_front_url',
        'id_card_back_url',
        'psych_neurology_certificate_url',
        'narcology_certificate_url',
        'pension_contributions_certificate_url'
    ]
    
    urls = {}
    
    for column in columns:
        result = db_session.execute(
            text(f"SELECT id, {column} FROM users WHERE {column} IS NOT NULL AND {column} != ''")
        )
        for row in result.fetchall():
            user_id, url = row
            if url and is_convertible_image(url):
                if url not in urls:
                    urls[url] = []
                urls[url].append({
                    'table': 'users',
                    'column': column,
                    'id': str(user_id),
                    'id_column': 'id'
                })
    
    return urls


def collect_urls_from_cars(db_session) -> Dict[str, List[dict]]:
    """Собрать URL изображений из таблицы cars (JSON поле photos)"""
    urls = {}
    
    result = db_session.execute(
        text("SELECT id, photos FROM cars WHERE photos IS NOT NULL")
    )
    
    for row in result.fetchall():
        car_id, photos = row
        if not photos:
            continue
        
        # photos может быть строкой JSON или списком
        try:
            if isinstance(photos, str):
                photos_list = json.loads(photos)
            else:
                photos_list = photos if photos else []
        except Exception:
            continue
        
        for idx, url in enumerate(photos_list):
            if url and is_convertible_image(url):
                if url not in urls:
                    urls[url] = []
                urls[url].append({
                    'table': 'cars',
                    'column': 'photos',
                    'id': str(car_id),
                    'id_column': 'id',
                    'array_index': idx,
                    'is_json': True
                })
    
    return urls


def collect_urls_from_rental_history(db_session) -> Dict[str, List[dict]]:
    """Собрать URL изображений из таблицы rental_history (ARRAY поля)"""
    columns = [
        'photos_before',
        'photos_after',
        'delivery_photos_before',
        'delivery_photos_after',
        'mechanic_photos_before',
        'mechanic_photos_after'
    ]
    
    urls = {}
    
    for column in columns:
        result = db_session.execute(
            text(f"SELECT id, {column} FROM rental_history WHERE {column} IS NOT NULL AND array_length({column}, 1) > 0")
        )
        
        for row in result.fetchall():
            rental_id, photos = row
            if not photos:
                continue
            
            for idx, url in enumerate(photos):
                if url and is_convertible_image(url):
                    if url not in urls:
                        urls[url] = []
                    urls[url].append({
                        'table': 'rental_history',
                        'column': column,
                        'id': str(rental_id),
                        'id_column': 'id',
                        'array_index': idx,
                        'is_array': True
                    })
    
    return urls


def collect_urls_from_support_messages(db_session) -> Dict[str, List[dict]]:
    """Собрать URL изображений из таблицы support_messages"""
    urls = {}
    
    result = db_session.execute(
        text("SELECT id, media_url FROM support_messages WHERE media_url IS NOT NULL AND media_url != ''")
    )
    
    for row in result.fetchall():
        msg_id, url = row
        if url and is_convertible_image(url):
            if url not in urls:
                urls[url] = []
            urls[url].append({
                'table': 'support_messages',
                'column': 'media_url',
                'id': str(msg_id),
                'id_column': 'id'
            })
    
    return urls


def collect_urls_from_contract_files(db_session) -> Dict[str, List[dict]]:
    """Собрать URL изображений из таблицы contract_files"""
    urls = {}
    
    try:
        result = db_session.execute(
            text("SELECT id, file_url FROM contract_files WHERE file_url IS NOT NULL AND file_url != ''")
        )
        
        for row in result.fetchall():
            file_id, url = row
            if url and is_convertible_image(url):
                if url not in urls:
                    urls[url] = []
                urls[url].append({
                    'table': 'contract_files',
                    'column': 'file_url',
                    'id': str(file_id),
                    'id_column': 'id'
                })
    except Exception as e:
        logger.warning(f"Таблица contract_files не найдена или ошибка: {e}")
    
    return urls


def collect_all_urls(db_session, tables: Optional[List[str]] = None) -> Dict[str, List[dict]]:
    """
    Собрать все URL изображений из БД.
    
    Returns:
        Dict[url, List[{table, column, id, ...}]] - маппинг URL на места использования
    """
    all_urls = {}
    
    collectors = {
        'users': collect_urls_from_users,
        'cars': collect_urls_from_cars,
        'rental_history': collect_urls_from_rental_history,
        'support_messages': collect_urls_from_support_messages,
        'contract_files': collect_urls_from_contract_files,
    }
    
    for table_name, collector in collectors.items():
        if tables and table_name not in tables:
            continue
        
        logger.info(f"Сканирование таблицы {table_name}...")
        table_urls = collector(db_session)
        
        for url, usages in table_urls.items():
            if url not in all_urls:
                all_urls[url] = []
            all_urls[url].extend(usages)
        
        logger.info(f"  Найдено {len(table_urls)} уникальных URL")
    
    return all_urls


# ============================================================
# ОБНОВЛЕНИЕ БД
# ============================================================

def update_db_url(db_session, old_url: str, new_url: str, usages: List[dict], dry_run: bool = False) -> int:
    """
    Обновить URL в БД для всех мест использования.
    
    Returns:
        Количество обновлённых записей
    """
    updated = 0
    
    for usage in usages:
        table = usage['table']
        column = usage['column']
        record_id = usage['id']
        id_column = usage.get('id_column', 'id')
        
        if dry_run:
            logger.info(f"    [DRY-RUN] {table}.{column} id={record_id}: {old_url} -> {new_url}")
            updated += 1
            continue
        
        try:
            if usage.get('is_json'):
                # JSON поле (cars.photos)
                # Получаем текущее значение
                result = db_session.execute(
                    text(f"SELECT {column} FROM {table} WHERE {id_column} = :id"),
                    {"id": record_id}
                )
                row = result.fetchone()
                if row and row[0]:
                    photos = row[0] if isinstance(row[0], list) else json.loads(row[0])
                    # Заменяем URL
                    new_photos = [new_url if p == old_url else p for p in photos]
                    db_session.execute(
                        text(f"UPDATE {table} SET {column} = :photos WHERE {id_column} = :id"),
                        {"photos": json.dumps(new_photos), "id": record_id}
                    )
                    updated += 1
                    
            elif usage.get('is_array'):
                # PostgreSQL ARRAY поле
                result = db_session.execute(
                    text(f"SELECT {column} FROM {table} WHERE {id_column} = :id"),
                    {"id": record_id}
                )
                row = result.fetchone()
                if row and row[0]:
                    photos = list(row[0])
                    # Заменяем URL
                    new_photos = [new_url if p == old_url else p for p in photos]
                    # Формируем PostgreSQL array literal
                    array_str = "{" + ",".join([f'"{url}"' for url in new_photos]) + "}"
                    db_session.execute(
                        text(f"UPDATE {table} SET {column} = :photos WHERE {id_column} = :id"),
                        {"photos": array_str, "id": record_id}
                    )
                    updated += 1
            else:
                # Простое строковое поле
                db_session.execute(
                    text(f"UPDATE {table} SET {column} = :new_url WHERE {id_column} = :id AND {column} = :old_url"),
                    {"new_url": new_url, "id": record_id, "old_url": old_url}
                )
                updated += 1
                
        except Exception as e:
            logger.error(f"    Ошибка обновления {table}.{column} id={record_id}: {e}")
    
    return updated


# ============================================================
# ОСНОВНАЯ ЛОГИКА КОНВЕРТАЦИИ
# ============================================================

def convert_and_update(
    db_session,
    s3_client,
    url: str,
    usages: List[dict],
    dry_run: bool = False,
    delete_old: bool = False
) -> dict:
    """
    Конвертировать один файл и обновить БД.
    
    Returns:
        Статистика операции
    """
    result = {
        'status': 'skipped',
        'original_size': 0,
        'new_size': 0,
        'db_updated': 0
    }
    
    # Парсим URL
    bucket, key = parse_minio_url(url)
    if not bucket or not key:
        logger.warning(f"  Не удалось распарсить URL: {url}")
        result['status'] = 'error'
        return result
    
    new_key = get_webp_key(key)
    new_url = get_webp_url(url)
    
    # Проверяем, существует ли уже WebP версия
    try:
        s3_client.head_object(Bucket=bucket, Key=new_key)
        logger.info(f"  ⏭️  WebP уже существует: {new_key}")
        # Обновляем БД на новый URL
        result['db_updated'] = update_db_url(db_session, url, new_url, usages, dry_run)
        result['status'] = 'exists'
        return result
    except ClientError:
        pass  # Файл не существует - будем создавать
    
    if dry_run:
        logger.info(f"  🔍 [DRY-RUN] Будет конвертирован: {key} -> {new_key}")
        result['status'] = 'would_convert'
        result['db_updated'] = update_db_url(db_session, url, new_url, usages, dry_run)
        return result
    
    # Скачиваем оригинал
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
    except ClientError as e:
        logger.error(f"  ❌ Файл не найден в MinIO: {key} ({e})")
        result['status'] = 'not_found'
        return result
    except Exception as e:
        logger.error(f"  ❌ Ошибка скачивания: {e}")
        result['status'] = 'error'
        return result
    
    # Конвертируем
    webp_content, original_size, new_size = convert_image_to_webp(content)
    
    if webp_content is None:
        logger.error(f"  ❌ Ошибка конвертации: {key}")
        result['status'] = 'error'
        return result
    
    # Загружаем WebP
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=new_key,
            Body=BytesIO(webp_content),
            ContentType='image/webp',
            ContentLength=new_size
        )
    except Exception as e:
        logger.error(f"  ❌ Ошибка загрузки WebP: {e}")
        result['status'] = 'error'
        return result
    
    savings = ((original_size - new_size) / original_size * 100) if original_size > 0 else 0
    logger.info(f"  ✅ Конвертирован: {key} -> {new_key} ({original_size:,} -> {new_size:,} байт, -{savings:.1f}%)")
    
    # Обновляем БД
    result['db_updated'] = update_db_url(db_session, url, new_url, usages, dry_run)
    
    # Удаляем оригинал если нужно
    if delete_old:
        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
            logger.info(f"  🗑️  Удалён оригинал: {key}")
        except Exception as e:
            logger.error(f"  ❌ Ошибка удаления оригинала: {e}")
    
    result['status'] = 'converted'
    result['original_size'] = original_size
    result['new_size'] = new_size
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Конвертация изображений в WebP (БД → MinIO)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Показать что будет сделано без реальных изменений'
    )
    parser.add_argument(
        '--delete-old',
        action='store_true',
        help='Удалить оригинальные файлы после конвертации'
    )
    parser.add_argument(
        '--table',
        type=str,
        help='Обработать только указанную таблицу (users, cars, rental_history, support_messages, contract_files)'
    )
    
    args = parser.parse_args()
    tables = [args.table] if args.table else None
    
    logger.info("=" * 70)
    logger.info("КОНВЕРТАЦИЯ ИЗОБРАЖЕНИЙ В WEBP")
    logger.info("Логика: БД → MinIO (сначала собираем URL из БД, потом конвертируем)")
    logger.info("=" * 70)
    logger.info(f"Dry-run: {args.dry_run}")
    logger.info(f"Delete old: {args.delete_old}")
    logger.info(f"Tables: {tables or 'все'}")
    logger.info("=" * 70)
    
    if args.delete_old and not args.dry_run:
        confirm = input("⚠️  ВНИМАНИЕ: Оригинальные файлы будут удалены! Продолжить? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("Отменено пользователем")
            return
    
    # Статистика
    stats = {
        'total_urls': 0,
        'converted': 0,
        'already_exists': 0,
        'not_found': 0,
        'errors': 0,
        'bytes_before': 0,
        'bytes_after': 0,
        'db_updated': 0
    }
    
    # Подключаемся к БД и MinIO
    logger.info("\nПодключение к БД и MinIO...")
    db_session = get_db_session()
    s3_client = get_s3_client()
    
    # Собираем все URL из БД
    logger.info("\n" + "=" * 70)
    logger.info("ШАГ 1: СБОР URL ИЗ БАЗЫ ДАННЫХ")
    logger.info("=" * 70)
    
    all_urls = collect_all_urls(db_session, tables)
    stats['total_urls'] = len(all_urls)
    
    logger.info(f"\nВсего найдено {len(all_urls)} уникальных URL для конвертации")
    
    if not all_urls:
        logger.info("Нет изображений для конвертации")
        return
    
    # Конвертируем каждый URL
    logger.info("\n" + "=" * 70)
    logger.info("ШАГ 2: КОНВЕРТАЦИЯ ФАЙЛОВ И ОБНОВЛЕНИЕ БД")
    logger.info("=" * 70)
    
    for i, (url, usages) in enumerate(all_urls.items(), 1):
        logger.info(f"\n[{i}/{len(all_urls)}] {url}")
        logger.info(f"  Используется в: {len(usages)} местах")
        
        result = convert_and_update(
            db_session=db_session,
            s3_client=s3_client,
            url=url,
            usages=usages,
            dry_run=args.dry_run,
            delete_old=args.delete_old
        )
        
        if result['status'] == 'converted':
            stats['converted'] += 1
            stats['bytes_before'] += result['original_size']
            stats['bytes_after'] += result['new_size']
        elif result['status'] == 'exists':
            stats['already_exists'] += 1
        elif result['status'] == 'not_found':
            stats['not_found'] += 1
        elif result['status'] == 'error':
            stats['errors'] += 1
        
        stats['db_updated'] += result['db_updated']
    
    # Коммитим изменения в БД
    if not args.dry_run:
        logger.info("\nСохранение изменений в БД...")
        db_session.commit()
    
    db_session.close()
    
    # Итоги
    logger.info("\n" + "=" * 70)
    logger.info("РЕЗУЛЬТАТЫ")
    logger.info("=" * 70)
    logger.info(f"Всего URL в БД: {stats['total_urls']}")
    logger.info(f"Конвертировано: {stats['converted']}")
    logger.info(f"Уже в WebP: {stats['already_exists']}")
    logger.info(f"Не найдено в MinIO: {stats['not_found']}")
    logger.info(f"Ошибок: {stats['errors']}")
    logger.info(f"Обновлено записей в БД: {stats['db_updated']}")
    
    if stats['bytes_before'] > 0:
        savings = stats['bytes_before'] - stats['bytes_after']
        savings_pct = (savings / stats['bytes_before']) * 100
        logger.info(f"\nРазмер до: {stats['bytes_before']:,} байт ({stats['bytes_before'] / 1024 / 1024:.2f} MB)")
        logger.info(f"Размер после: {stats['bytes_after']:,} байт ({stats['bytes_after'] / 1024 / 1024:.2f} MB)")
        logger.info(f"Экономия: {savings:,} байт ({savings_pct:.1f}%)")
    
    logger.info("=" * 70)


if __name__ == '__main__':
    main()
