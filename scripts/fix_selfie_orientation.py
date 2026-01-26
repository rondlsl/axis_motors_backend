#!/usr/bin/env python3
"""
Скрипт для исправления ориентации селфи.
Переконвертирует селфи из оригиналов (jpg/png) в WebP с правильной EXIF ориентацией.

Запуск:
    python scripts/fix_selfie_orientation.py --dry-run
    python scripts/fix_selfie_orientation.py
"""
import os
import sys
import argparse
import logging
from io import BytesIO
from typing import List, Tuple, Optional, Dict
from collections import defaultdict
import time
import threading

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig
from PIL import Image, ImageOps
from sqlalchemy import create_engine, text

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# Импорт конфигурации
from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
)

# Пробуем получить DATABASE_URL
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

# Цвета для терминала
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

WEBP_QUALITY = 85
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}

# Колонки с селфи в users
USER_SELFIE_COLUMNS = ['selfie_url', 'selfie_with_license_url']

# Колонки с фото в rental_history (содержат селфи в подпапке /selfie/)
RENTAL_PHOTO_COLUMNS = [
    'photos_before', 'photos_after',
    'delivery_photos_before', 'delivery_photos_after',
    'mechanic_photos_before', 'mechanic_photos_after'
]


class ProgressTracker:
    """Трекер прогресса с live-статистикой"""
    
    def __init__(self, total: int, dry_run: bool = False):
        self.total = total
        self.dry_run = dry_run
        self.processed = 0
        self.fixed = 0
        self.no_original = 0
        self.errors = 0
        self.bytes_before = 0
        self.bytes_after = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
        
        # Статистика по таблицам/колонкам
        self.by_table: Dict[str, int] = defaultdict(int)
        self.by_column: Dict[str, int] = defaultdict(int)
        self.by_status: Dict[str, int] = defaultdict(int)
    
    def update(self, result: dict, selfie: dict):
        with self.lock:
            self.processed += 1
            status = result.get('status', 'error')
            self.by_status[status] += 1
            
            table = selfie.get('table', 'unknown')
            column = selfie.get('column', 'unknown')
            
            if status in ('fixed', 'would_fix'):
                self.fixed += 1
                self.by_table[table] += 1
                self.by_column[column] += 1
                if 'original_size' in result:
                    self.bytes_before += result['original_size']
                    self.bytes_after += result['new_size']
            elif status == 'no_original':
                self.no_original += 1
            else:
                self.errors += 1
    
    def get_eta(self) -> str:
        """Получить ETA"""
        if self.processed == 0:
            return "calculating..."
        
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed
        remaining = self.total - self.processed
        eta_seconds = remaining / rate if rate > 0 else 0
        
        if eta_seconds < 60:
            return f"{eta_seconds:.0f}s"
        elif eta_seconds < 3600:
            return f"{eta_seconds/60:.1f}m"
        else:
            return f"{eta_seconds/3600:.1f}h"
    
    def get_speed(self) -> str:
        """Получить скорость"""
        elapsed = time.time() - self.start_time
        if elapsed == 0:
            return "0/s"
        rate = self.processed / elapsed
        return f"{rate:.1f}/s"
    
    def get_progress_bar(self, width: int = 30) -> str:
        """Получить прогресс-бар"""
        if self.total == 0:
            return "█" * width
        
        filled = int(width * self.processed / self.total)
        empty = width - filled
        percentage = (self.processed / self.total) * 100
        
        bar = "█" * filled + "░" * empty
        return f"[{bar}] {percentage:5.1f}%"
    
    def print_status(self):
        """Вывести текущий статус"""
        elapsed = time.time() - self.start_time
        
        # Очистка строки и возврат курсора
        sys.stdout.write('\r\033[K')
        
        status_parts = [
            f"{Colors.CYAN}{self.get_progress_bar()}{Colors.END}",
            f"{Colors.BOLD}{self.processed}/{self.total}{Colors.END}",
            f"{Colors.GREEN}✓{self.fixed}{Colors.END}",
            f"{Colors.YELLOW}⚠{self.no_original}{Colors.END}",
            f"{Colors.RED}✗{self.errors}{Colors.END}",
            f"⏱{self.get_speed()}",
            f"ETA:{self.get_eta()}"
        ]
        
        sys.stdout.write(" ".join(status_parts))
        sys.stdout.flush()
    
    def print_final_report(self):
        """Вывести финальный отчёт"""
        elapsed = time.time() - self.start_time
        
        print("\n")
        print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}  📊 РЕЗУЛЬТАТЫ {'(DRY-RUN)' if self.dry_run else ''}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
        
        # Основная статистика
        print(f"\n{Colors.BOLD}  ⏱  Время:{Colors.END} {elapsed:.1f} сек ({elapsed/60:.1f} мин)")
        print(f"{Colors.BOLD}  📁 Всего:{Colors.END} {self.total} селфи")
        print(f"{Colors.BOLD}  ⚡ Скорость:{Colors.END} {self.processed/elapsed:.1f} файлов/сек")
        
        # Статусы
        print(f"\n{Colors.BOLD}  📈 Статусы:{Colors.END}")
        print(f"     {Colors.GREEN}✓ Исправлено:{Colors.END} {self.fixed}")
        print(f"     {Colors.YELLOW}⚠ Оригинал не найден:{Colors.END} {self.no_original}")
        print(f"     {Colors.RED}✗ Ошибок:{Colors.END} {self.errors}")
        
        # По таблицам
        if self.by_table:
            print(f"\n{Colors.BOLD}  📋 По таблицам:{Colors.END}")
            for table, count in sorted(self.by_table.items(), key=lambda x: -x[1]):
                print(f"     • {table}: {count}")
        
        # По колонкам
        if self.by_column:
            print(f"\n{Colors.BOLD}  📝 По колонкам:{Colors.END}")
            for col, count in sorted(self.by_column.items(), key=lambda x: -x[1]):
                print(f"     • {col}: {count}")
        
        # Размеры
        if self.bytes_before > 0:
            savings = self.bytes_before - self.bytes_after
            savings_pct = (savings / self.bytes_before) * 100 if self.bytes_before > 0 else 0
            
            print(f"\n{Colors.BOLD}  💾 Размеры:{Colors.END}")
            print(f"     До:    {self.bytes_before/1024/1024:.1f} MB")
            print(f"     После: {self.bytes_after/1024/1024:.1f} MB")
            print(f"     {Colors.GREEN}Экономия: {savings/1024/1024:.1f} MB ({savings_pct:.1f}%){Colors.END}")
        
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}\n")


def get_s3_client():
    """Создать клиент S3/MinIO"""
    return boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
            retries={'max_attempts': 3}
        )
    )


def get_db_engine():
    """Создать engine БД"""
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def parse_db_path(db_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Извлечь bucket и key из пути/URL в БД"""
    if not db_path:
        return None, None
    
    try:
        path = db_path
        
        if path.startswith('http://') or path.startswith('https://'):
            path = path.split('://', 1)[1]
            path = path.split('/', 1)[1] if '/' in path else ''
        
        path = path.lstrip('/')
        
        if not path:
            return None, None
        
        parts = path.split('/', 1)
        
        if len(parts) < 2:
            return None, None
        
        return parts[0], parts[1]
    except Exception:
        return None, None


def get_original_key(webp_key: str) -> List[str]:
    """Получить возможные ключи оригинала для webp файла"""
    base = webp_key.rsplit('.webp', 1)[0]
    return [f"{base}.jpg", f"{base}.jpeg", f"{base}.png", f"{base}.JPG", f"{base}.JPEG", f"{base}.PNG"]


def convert_with_exif(content: bytes) -> Optional[bytes]:
    """Конвертировать изображение в WebP с учётом EXIF ориентации"""
    try:
        img = Image.open(BytesIO(content))
        
        # КЛЮЧЕВОЕ: применяем EXIF ориентацию
        img = ImageOps.exif_transpose(img)
        
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
        img.save(output, format='WEBP', quality=WEBP_QUALITY, method=4)
        output.seek(0)
        
        return output.getvalue()
    except Exception as e:
        return None


def collect_selfie_urls(engine) -> List[dict]:
    """Собрать все селфи URL из БД (users + rental_history)"""
    selfies = []
    
    print(f"\n{Colors.BOLD}{Colors.BLUE}📂 Сканирование базы данных...{Colors.END}\n")
    
    with engine.connect() as conn:
        # 1. Селфи из users
        for col in USER_SELFIE_COLUMNS:
            sys.stdout.write(f"  {Colors.CYAN}→{Colors.END} users.{col}...")
            sys.stdout.flush()
            
            result = conn.execute(text(
                f"SELECT id, {col} FROM users WHERE {col} IS NOT NULL AND {col} != '' AND {col} LIKE '%.webp'"
            ))
            
            count = 0
            for row in result.fetchall():
                user_id, url = row
                if url:
                    selfies.append({
                        'table': 'users',
                        'record_id': str(user_id),
                        'column': col,
                        'webp_url': url
                    })
                    count += 1
            
            print(f" {Colors.GREEN}{count}{Colors.END} найдено")
        
        # 2. Селфи из rental_history (фильтр по /selfie/ в пути)
        for col in RENTAL_PHOTO_COLUMNS:
            sys.stdout.write(f"  {Colors.CYAN}→{Colors.END} rental_history.{col}...")
            sys.stdout.flush()
            
            try:
                result = conn.execute(text(
                    f"SELECT id, {col} FROM rental_history WHERE {col} IS NOT NULL AND array_length({col}, 1) > 0"
                ))
                
                col_count = 0
                for row in result.fetchall():
                    rental_id, photos = row
                    if not photos:
                        continue
                    
                    for idx, url in enumerate(photos):
                        # Только селфи (содержат /selfie/ в пути) и уже .webp
                        if url and '/selfie/' in url and url.endswith('.webp'):
                            selfies.append({
                                'table': 'rental_history',
                                'record_id': str(rental_id),
                                'column': col,
                                'array_index': idx,
                                'webp_url': url
                            })
                            col_count += 1
                
                print(f" {Colors.GREEN}{col_count}{Colors.END} найдено")
            except Exception as e:
                print(f" {Colors.RED}ошибка: {e}{Colors.END}")
    
    return selfies


def fix_single_selfie(s3_client, selfie: dict, dry_run: bool) -> dict:
    """Исправить ориентацию одного селфи"""
    webp_url = selfie['webp_url']
    
    # Парсим путь
    bucket, webp_key = parse_db_path(webp_url)
    if not bucket or not webp_key:
        return {'status': 'error', 'error': 'Invalid path'}
    
    # Ищем оригинал
    original_keys = get_original_key(webp_key)
    original_content = None
    found_key = None
    
    for orig_key in original_keys:
        try:
            response = s3_client.get_object(Bucket=bucket, Key=orig_key)
            original_content = response['Body'].read()
            found_key = orig_key
            break
        except ClientError:
            continue
    
    if not original_content:
        return {'status': 'no_original', 'error': f'Original not found for {webp_key}'}
    
    if dry_run:
        return {'status': 'would_fix', 'original': found_key}
    
    # Конвертируем с правильной ориентацией
    webp_content = convert_with_exif(original_content)
    if not webp_content:
        return {'status': 'error', 'error': 'Conversion failed'}
    
    # Перезаписываем webp файл
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=webp_key,
            Body=BytesIO(webp_content),
            ContentType='image/webp',
            ContentLength=len(webp_content)
        )
    except Exception as e:
        return {'status': 'error', 'error': f'Upload failed: {e}'}
    
    return {
        'status': 'fixed',
        'original_size': len(original_content),
        'new_size': len(webp_content),
        'table': selfie.get('table'),
        'column': selfie.get('column')
    }


def main():
    parser = argparse.ArgumentParser(description='Исправление ориентации селфи')
    parser.add_argument('--dry-run', action='store_true', help='Без реальных изменений')
    args = parser.parse_args()
    
    # Заголовок
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}  🖼️  ИСПРАВЛЕНИЕ ОРИЕНТАЦИИ СЕЛФИ {'(DRY-RUN)' if args.dry_run else ''}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 70}{Colors.END}")
    
    print(f"\n{Colors.BOLD}  📋 Источники:{Colors.END}")
    print(f"     • users: {', '.join(USER_SELFIE_COLUMNS)}")
    print(f"     • rental_history: {len(RENTAL_PHOTO_COLUMNS)} колонок (только /selfie/)")
    
    # Подключение к БД
    print(f"\n{Colors.BOLD}{Colors.BLUE}🔌 Подключение к БД...{Colors.END}")
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"  {Colors.GREEN}✓ Подключено{Colors.END}")
    except Exception as e:
        print(f"  {Colors.RED}✗ Ошибка: {e}{Colors.END}")
        return
    
    # Сбор селфи
    selfies = collect_selfie_urls(engine)
    
    print(f"\n{Colors.BOLD}  📊 Всего селфи для обработки: {Colors.YELLOW}{len(selfies)}{Colors.END}")
    
    if not selfies:
        print(f"\n{Colors.GREEN}✓ Нет селфи для исправления{Colors.END}\n")
        return
    
    # Исправление
    print(f"\n{Colors.BOLD}{Colors.BLUE}🔧 Обработка файлов...{Colors.END}\n")
    
    s3_client = get_s3_client()
    tracker = ProgressTracker(len(selfies), args.dry_run)
    
    for selfie in selfies:
        result = fix_single_selfie(s3_client, selfie, args.dry_run)
        tracker.update(result, selfie)
        tracker.print_status()
    
    # Финальный отчёт
    tracker.print_final_report()


if __name__ == '__main__':
    main()
