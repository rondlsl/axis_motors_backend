#!/usr/bin/env python3
"""
Скрипт для машины, у которой в БД уже прописаны пути .webp, а в MinIO лежат ещё .jpeg.
Скачивает .jpeg/.jpg из MinIO, конвертирует в WebP и загружает под ключом .webp.
БД не меняет — пути уже .webp.

Запуск:
    python scripts/convert_car_photos_jpeg_to_webp.py
    python scripts/convert_car_photos_jpeg_to_webp.py --car-id 11082b5c-1550-481c-a6da-8a0bb7aee4a2
    python scripts/convert_car_photos_jpeg_to_webp.py --dry-run
"""
import os
import sys
import argparse
import logging
import json
from io import BytesIO
from typing import List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig
from PIL import Image, ImageOps
from sqlalchemy import create_engine, text

from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
)

try:
    from app.core.config import DATABASE_URL
except Exception:
    DATABASE_URL = None
if not DATABASE_URL or 'None' in str(DATABASE_URL):
    from app.core.config import (
        POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
    )
    if all([POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB]):
        DATABASE_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    else:
        DATABASE_URL = os.getenv(
            'DATABASE_URL',
            'postgresql+psycopg2://postgres:postgres@localhost:5432/azv_motors_backend_v2'
        )

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WEBP_QUALITY = 85
DEFAULT_CAR_ID = '11082b5c-1550-481c-a6da-8a0bb7aee4a2'


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(signature_version='s3v4', s3={'addressing_style': 'path'})
    )


def parse_db_path(db_path: str) -> Tuple[Optional[str], Optional[str]]:
    if not db_path:
        return None, None
    try:
        path = db_path.strip()
        if path.startswith('http://') or path.startswith('https://'):
            path = path.split('://', 1)[1].split('/', 1)[-1]
        path = path.lstrip('/')
        if not path:
            return None, None
        parts = path.split('/', 1)
        if len(parts) < 2:
            return None, None
        return parts[0], parts[1]
    except Exception:
        return None, None


def convert_image_to_webp(content: bytes) -> Tuple[Optional[bytes], int, int]:
    try:
        original_size = len(content)
        img = Image.open(BytesIO(content))
        img = ImageOps.exif_transpose(img)
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
        img.save(output, format='WEBP', quality=WEBP_QUALITY, method=4)
        output.seek(0)
        webp_content = output.getvalue()
        return webp_content, original_size, len(webp_content)
    except Exception as e:
        logger.debug(f"Ошибка конвертации: {e}")
        return None, 0, 0


def collect_car_photo_urls(engine, car_id: str) -> List[str]:
    """Собрать все URL фотографий машины: cars.photos + rental_history по car_id."""
    urls = []
    with engine.connect() as conn:
        # cars.photos (JSON)
        row = conn.execute(
            text("SELECT photos FROM cars WHERE id = :id"),
            {"id": car_id}
        ).fetchone()
        if row and row[0]:
            photos = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or [])
            urls.extend(p for p in photos if p and isinstance(p, str))

        # rental_history: все поля с фотками по car_id
        for col in (
            'photos_before', 'photos_after',
            'delivery_photos_before', 'delivery_photos_after',
            'mechanic_photos_before', 'mechanic_photos_after'
        ):
            try:
                result = conn.execute(
                    text(
                        f"SELECT {col} FROM rental_history WHERE car_id = :cid AND {col} IS NOT NULL AND array_length({col}, 1) > 0"
                    ),
                    {"cid": car_id}
                )
                for row in result.fetchall():
                    if row[0]:
                        urls.extend(p for p in row[0] if p and isinstance(p, str))
            except Exception as e:
                logger.debug(f"Ошибка по колонке {col}: {e}")
    return list(dict.fromkeys(urls))


def ensure_webp_from_jpeg(db_path: str, dry_run: bool) -> Tuple[str, Optional[str]]:
    """
    Для пути из БД (уже .webp): если в MinIO нет .webp, ищем .jpeg/.jpg,
    конвертируем в WebP и заливаем под .webp. БД не трогаем.
    Возвращает (status, error_msg): status in ('ok', 'exists', 'converted', 'not_found', 'error').
    """
    bucket, key = parse_db_path(db_path)
    if not bucket or not key:
        return 'error', 'Invalid path'

    s3 = get_s3_client()
    key_lower = key.lower()
    if not key_lower.endswith('.webp'):
        return 'skipped', 'Path is not .webp, run convert_images_to_webp.py'

    # уже есть webp
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return 'exists', None
    except ClientError:
        pass

    base, _ = os.path.splitext(key)
    for ext in ('.jpeg', '.jpg', '.JPG', '.JPEG'):
        src_key = base + ext
        try:
            s3.head_object(Bucket=bucket, Key=src_key)
            break
        except ClientError:
            continue
    else:
        return 'not_found', f'No .webp and no .jpeg/.jpg for {key}'

    if dry_run:
        return 'would_convert', None

    try:
        resp = s3.get_object(Bucket=bucket, Key=src_key)
        content = resp['Body'].read()
    except Exception as e:
        return 'error', str(e)

    webp_content, _, new_size = convert_image_to_webp(content)
    if webp_content is None:
        return 'error', 'Conversion failed'

    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=BytesIO(webp_content),
            ContentType='image/webp',
            ContentLength=new_size
        )
    except Exception as e:
        return 'error', f'Upload failed: {e}'

    return 'converted', None


def main():
    parser = argparse.ArgumentParser(description='Дозаполнить WebP для машины из имеющихся JPEG')
    parser.add_argument('--car-id', default=DEFAULT_CAR_ID, help=f'UUID машины (default: {DEFAULT_CAR_ID})')
    parser.add_argument('--dry-run', action='store_true', help='Только показать, что будет сделано')
    args = parser.parse_args()

    logger.info("Car ID: %s", args.car_id)
    logger.info("Dry-run: %s", args.dry_run)

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    urls = collect_car_photo_urls(engine, args.car_id)
    logger.info("Найдено URL фотографий: %s", len(urls))

    exists = converted = not_found = errors = skipped = 0
    for url in urls:
        status, err = ensure_webp_from_jpeg(url, args.dry_run)
        if status == 'exists':
            exists += 1
        elif status == 'converted' or status == 'would_convert':
            converted += 1
            if status == 'converted':
                logger.info("Converted: %s", url)
        elif status == 'not_found':
            not_found += 1
            logger.warning("Not found (no jpeg): %s — %s", url, err or '')
        elif status == 'error':
            errors += 1
            logger.warning("Error: %s — %s", url, err or '')
        else:
            skipped += 1

    logger.info("— exists/skip: %s, converted/would: %s, not_found: %s, errors: %s, skipped: %s",
                exists, converted, not_found, errors, skipped)


if __name__ == '__main__':
    main()
