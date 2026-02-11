#!/usr/bin/env python3
"""
Production-ready скрипт для удаления "осиротевших" изображений из MinIO.

Скрипт находит все JPEG файлы в MinIO, которые не связаны с записями в БД,
и удаляет их с возможностью предварительного просмотра (DRY_RUN mode).

Author: Senior Backend Engineer
Requirements: Python 3.10+, minio, sqlalchemy/psycopg2
"""

import os
import sys
import logging
from typing import Set, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Добавляем путь к проекту для импортов
sys.path.insert(0, str(Path(__file__).parent.parent))

from minio import Minio
from minio.error import S3Error
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_USE_SSL,
    DATABASE_URL
)


@dataclass
class CleanupStats:
    """Статистика операции очистки."""
    total_objects_found: int = 0
    jpeg_objects_found: int = 0
    db_files_found: int = 0
    orphaned_files: int = 0
    deleted_files: int = 0
    errors: int = 0


class MinIOCleanupService:
    """Сервис для очистки MinIO от неиспользуемых файлов."""
    
    def __init__(self, bucket_name: str = "uploads", dry_run: bool = True, max_workers: int = 10):
        self.bucket_name = bucket_name
        self.dry_run = dry_run
        self.max_workers = max_workers
        self.stats = CleanupStats()
        self.logger = self._setup_logger()
        
        # Thread-safe stats tracking
        self._stats_lock = threading.Lock()
        
        # Инициализация клиентов
        self.minio_client = None
        self.db_engine = None
        self.db_session = None
        
    def _setup_logger(self) -> logging.Logger:
        """Настройка логирования."""
        logger = logging.getLogger("minio_cleanup")
        logger.setLevel(logging.INFO)
        
        # Консольный обработчик
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Файловый обработчик (опционально)
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            file_handler = logging.FileHandler(
                log_dir / f"cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Failed to create file logger: {e}")
        
        return logger
    
    def connect_minio(self) -> bool:
        """Подключение к MinIO."""
        try:
            # Extract host from endpoint (remove path if present)
            from urllib.parse import urlparse
            parsed_url = urlparse(MINIO_ENDPOINT)
            endpoint_host = parsed_url.netloc
            
            self.logger.info(f"Connecting to MinIO: {MINIO_ENDPOINT} -> {endpoint_host}")
            
            self.minio_client = Minio(
                endpoint=endpoint_host,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_USE_SSL
            )
            
            # Проверяем существование бакета
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.logger.error(f"Bucket '{self.bucket_name}' does not exist")
                return False
                
            self.logger.info(f"Successfully connected to MinIO, bucket: {self.bucket_name}")
            return True
            
        except S3Error as e:
            self.logger.error(f"MinIO connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected MinIO error: {e}")
            return False
    
    def connect_database(self) -> bool:
        """Подключение к базе данных."""
        try:
            self.logger.info("Connecting to database...")
            
            # Создаем engine с оптимизированными параметрами
            self.db_engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            
            # Создаем сессию
            SessionLocal = sessionmaker(bind=self.db_engine)
            self.db_session = SessionLocal()
            
            # Тестовое подключение
            self.db_session.execute(text("SELECT 1"))
            
            self.logger.info("Successfully connected to database")
            return True
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database connection error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected database error: {e}")
            return False
    
    def get_all_minio_objects(self) -> Dict[str, Set[str]]:
        """Получение всех объектов из MinIO с группировкой по папкам."""
        folders = {}
        
        try:
            self.logger.info(f"Listing objects in bucket '{self.bucket_name}'...")
            
            # Используем pager для обработки больших бакетов
            objects_list = self.minio_client.list_objects(
                bucket_name=self.bucket_name,
                recursive=True
            )
            
            for obj in objects_list:
                self.stats.total_objects_found += 1
                
                # Определяем папку и имя файла
                if '/' in obj.object_name:
                    folder = obj.object_name.rsplit('/', 1)[0]
                    filename = obj.object_name.rsplit('/', 1)[1]
                else:
                    folder = 'root'
                    filename = obj.object_name
                
                # Пропускаем папки supports и support
                if folder.startswith('support') or folder == 'support':
                    continue
                
                # Инициализируем папку если нужно
                if folder not in folders:
                    folders[folder] = {'jpeg': set(), 'webp': set(), 'all': set()}
                
                # Добавляем файл в соответствующую категорию
                folders[folder]['all'].add(obj.object_name)
                
                if filename.lower().endswith(('.jpg', '.jpeg')):
                    folders[folder]['jpeg'].add(obj.object_name)
                    self.stats.jpeg_objects_found += 1
                elif filename.lower().endswith('.webp'):
                    folders[folder]['webp'].add(obj.object_name)
                    
            self.logger.info(f"Found {self.stats.total_objects_found} total objects, "
                           f"{self.stats.jpeg_objects_found} JPEG files in {len(folders)} folders")
            
        except S3Error as e:
            self.logger.error(f"Error listing MinIO objects: {e}")
            self.stats.errors += 1
        except Exception as e:
            self.logger.error(f"Unexpected error listing objects: {e}")
            self.stats.errors += 1
        
        return folders
    
    def get_all_db_files(self) -> Dict[str, Set[str]]:
        """Получение всех файлов из базы данных с разделением по типам."""
        all_files = set()
        
        try:
            self.logger.info("Querying database for valid files...")
            
            # Универсальный запрос для разных таблиц с обработкой ошибок
            queries = [
                # Таблица users (проверяем существующие колонки)
                "SELECT avatar_url FROM users WHERE avatar_url IS NOT NULL AND avatar_url != ''",
                "SELECT profile_photo FROM users WHERE profile_photo IS NOT NULL AND profile_photo != ''",
                # Таблица cars (фотографии)
                "SELECT main_photo FROM cars WHERE main_photo IS NOT NULL AND main_photo != ''",
                "SELECT photo FROM cars WHERE photo IS NOT NULL AND photo != ''",
                # Таблица wallet_transactions (чеки)
                "SELECT receipt_url FROM wallet_transactions WHERE receipt_url IS NOT NULL AND receipt_url != ''",
                # Таблица support_messages (вложения)
                "SELECT attachments FROM support_messages WHERE attachments IS NOT NULL AND attachments != ''",
                # Таблица contract_files
                "SELECT file_url FROM contract_files WHERE file_url IS NOT NULL AND file_url != ''",
                # Таблица rental_history (фото)
                "SELECT start_photo, end_photo FROM rental_history WHERE start_photo IS NOT NULL OR end_photo IS NOT NULL",
                # Таблица device_photos
                "SELECT photo_url FROM device_photos WHERE photo_url IS NOT NULL AND photo_url != ''",
            ]
            
            for query in queries:
                try:
                    result = self.db_session.execute(text(query))
                    
                    for row in result:
                        # Обрабатываем разные типы полей
                        for value in row:
                            if value:
                                # Если это JSON (как в attachments)
                                if isinstance(value, (dict, list)):
                                    if isinstance(value, list):
                                        for item in value:
                                            if isinstance(item, str) and item.strip():
                                                all_files.add(item.strip())
                                elif isinstance(value, str):
                                    all_files.add(value.strip())
                                    
                except Exception as e:
                    self.logger.warning(f"Error executing query '{query}': {e}")
                    # Rollback transaction on error
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    # Continue with next query
                    continue
            
            # Дополнительно ищем в JSON полях
            json_queries = [
                "SELECT documents FROM users WHERE documents IS NOT NULL",
                "SELECT attachments FROM support_chats WHERE attachments IS NOT NULL",
            ]
            
            for query in json_queries:
                try:
                    result = self.db_session.execute(text(query))
                    
                    for row in result:
                        if row[0]:
                            # Парсим JSON и извлекаем URL
                            import json
                            try:
                                docs = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                                if isinstance(docs, dict):
                                    for key, value in docs.items():
                                        if isinstance(value, str) and value.strip():
                                            all_files.add(value.strip())
                                elif isinstance(docs, list):
                                    for item in docs:
                                        if isinstance(item, str) and item.strip():
                                            all_files.add(item.strip())
                            except (json.JSONDecodeError, TypeError):
                                pass
                                
                except Exception as e:
                    self.logger.warning(f"Error parsing JSON for query '{query}': {e}")
                    # Rollback transaction on error
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    continue
            
            # Разделяем файлы по типам
            jpeg_files = {f for f in all_files if f.lower().endswith(('.jpg', '.jpeg'))}
            webp_files = {f for f in all_files if f.lower().endswith('.webp')}
            
            self.stats.db_files_found = len(jpeg_files)
            
            self.logger.info(f"Found {len(all_files)} total files in DB, "
                           f"{len(jpeg_files)} JPEG, {len(webp_files)} WebP files")
            
            return {
                'jpeg': jpeg_files,
                'webp': webp_files,
                'all': all_files
            }
            
        except SQLAlchemyError as e:
            self.logger.error(f"Database query error: {e}")
            self.stats.errors += 1
        except Exception as e:
            self.logger.error(f"Unexpected database error: {e}")
            self.stats.errors += 1
        
        return {'jpeg': set(), 'webp': set(), 'all': set()}
    
    def find_orphaned_files(self, minio_folders: Dict[str, Dict[str, Set[str]]], db_files: Dict[str, Set[str]]) -> Set[str]:
        """Поиск файлов для удаления с учетом webp в БД."""
        files_to_delete = set()
        
        for folder_name, folder_data in minio_folders.items():
            # Пропускаем папки supports и support
            if folder_name.startswith('support') or folder_name == 'support':
                self.logger.debug(f"Skipping protected folder: {folder_name}")
                continue
                
            jpeg_files = folder_data['jpeg']
            webp_files = folder_data['webp']
            
            if not jpeg_files:
                continue  # Нет JPEG файлов в папке
            
            self.logger.debug(f"Processing folder: {folder_name}")
            self.logger.debug(f"  JPEG files: {len(jpeg_files)}")
            self.logger.debug(f"  WebP files: {len(webp_files)}")
            
            # Проверяем есть ли WebP файлы из этой же папки в БД
            webp_in_db = set()
            for webp_path in webp_files:
                if webp_path in db_files['webp']:
                    webp_in_db.add(webp_path)
            
            if webp_in_db:
                self.logger.info(f"Folder {folder_name}: found {len(webp_in_db)} WebP files in DB")
                
                # Если есть WebP в БД, удаляем все JPEG из этой папки
                for jpeg_file in jpeg_files:
                    # Проверяем что JPEG нет в БД (дополнительная проверка)
                    if jpeg_file not in db_files['jpeg']:
                        files_to_delete.add(jpeg_file)
                        self.logger.debug(f"  Marked for deletion: {jpeg_file} (WebP exists in DB)")
            else:
                # Если нет WebP в БД, удаляем только те JPEG которых нет в БД
                for jpeg_file in jpeg_files:
                    if jpeg_file not in db_files['jpeg']:
                        files_to_delete.add(jpeg_file)
                        self.logger.debug(f"  Marked for deletion: {jpeg_file} (not in DB)")
        
        self.stats.orphaned_files = len(files_to_delete)
        
        self.logger.info(f"Found {self.stats.orphaned_files} files to delete")
        
        if files_to_delete and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("Files to delete:")
            for file in sorted(files_to_delete):
                self.logger.debug(f"  - {file}")
        
        return files_to_delete
    
    def _delete_single_file(self, file_name: str) -> tuple:
        """Удаление одного файла (thread-safe)."""
        try:
            if self.dry_run:
                return (file_name, True, None, "DRY_RUN")
            else:
                # Реальное удаление
                self.minio_client.remove_object(
                    bucket_name=self.bucket_name,
                    object_name=file_name
                )
                return (file_name, True, None, "DELETED")
                
        except S3Error as e:
            return (file_name, False, str(e), "S3_ERROR")
        except Exception as e:
            return (file_name, False, str(e), "UNEXPECTED_ERROR")
    
    def delete_files(self, files: Set[str]) -> None:
        """Параллельное удаление файлов из MinIO."""
        if not files:
            self.logger.info("No files to delete")
            return
        
        self.logger.info(f"{'[DRY RUN] Would delete' if self.dry_run else 'Deleting'} "
                        f"{len(files)} files from MinIO using {self.max_workers} threads...")
        
        deleted_count = 0
        error_count = 0
        
        # Разделяем файлы на чанки для лучшей производительности
        chunk_size = max(1, len(files) // self.max_workers)
        file_chunks = [list(files)[i:i + chunk_size] for i in range(0, len(files), chunk_size)]
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Отправляем задачи на удаление
            future_to_chunk = {
                executor.submit(self._process_file_chunk, chunk): chunk 
                for chunk in file_chunks
            }
            
            # Обрабатываем результаты
            for future in as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                try:
                    chunk_deleted, chunk_errors = future.result()
                    with self._stats_lock:
                        deleted_count += chunk_deleted
                        error_count += chunk_errors
                        self.stats.deleted_files += chunk_deleted
                        self.stats.errors += chunk_errors
                except Exception as e:
                    self.logger.error(f"Chunk processing error: {e}")
                    with self._stats_lock:
                        error_count += len(chunk)
                        self.stats.errors += len(chunk)
        
        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would delete {deleted_count} files")
        else:
            self.logger.info(f"Successfully deleted {deleted_count} files, "
                           f"{error_count} errors")
    
    def _process_file_chunk(self, file_chunk: List[str]) -> tuple:
        """Обработка чанка файлов (thread-safe)."""
        chunk_deleted = 0
        chunk_errors = 0
        
        for file_name in file_chunk:
            file_name, success, error, status = self._delete_single_file(file_name)
            
            if success:
                chunk_deleted += 1
                if status == "DELETED":
                    self.logger.debug(f"Deleted: {file_name}")
                elif status == "DRY_RUN":
                    self.logger.info(f"[DRY RUN] Would delete: {file_name}")
            else:
                chunk_errors += 1
                self.logger.error(f"Failed to delete {file_name}: {error}")
        
        return chunk_deleted, chunk_errors
    
    def print_summary(self) -> None:
        """Вывод итоговой статистики."""
        self.logger.info("=" * 60)
        self.logger.info("CLEANUP SUMMARY")
        self.logger.info("=" * 60)
        self.logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        self.logger.info(f"Threads used: {self.max_workers}")
        self.logger.info(f"Total objects in MinIO: {self.stats.total_objects_found}")
        self.logger.info(f"JPEG objects found: {self.stats.jpeg_objects_found}")
        self.logger.info(f"Valid JPEG files in DB: {self.stats.db_files_found}")
        self.logger.info(f"Files to delete: {self.stats.orphaned_files}")
        self.logger.info(f"Files deleted: {self.stats.deleted_files}")
        self.logger.info(f"Errors encountered: {self.stats.errors}")
        
        if self.stats.orphaned_files > 0 and self.stats.jpeg_objects_found > 0:
            percentage = (self.stats.orphaned_files / self.stats.jpeg_objects_found) * 100
            self.logger.info(f"Deletion percentage: {percentage:.2f}%")
        
        self.logger.info("=" * 60)
        self.logger.info("LOGIC: Files deleted if:")
        self.logger.info("  - JPEG not in DB AND no WebP from same folder in DB")
        self.logger.info("  - OR JPEG not in DB (standard orphaned)")
        self.logger.info("  - Skipped: supports/ folder")
        self.logger.info("=" * 60)
    
    def cleanup(self) -> bool:
        """Основной метод очистки."""
        start_time = datetime.now()
        
        try:
            self.logger.info(f"Starting MinIO cleanup (DRY_RUN={self.dry_run})")
            
            # Подключение к сервисам
            if not self.connect_minio():
                return False
            
            if not self.connect_database():
                return False
            
            # Получение данных
            minio_folders = self.get_all_minio_objects()
            if not minio_folders:
                self.logger.warning("No files found in MinIO")
                return True
            
            db_files = self.get_all_db_files()
            
            # Поиск и удаление осиротевших файлов
            orphaned_files = self.find_orphaned_files(minio_folders, db_files)
            self.delete_files(orphaned_files)
            
            # Вывод статистики
            self.print_summary()
            
            duration = datetime.now() - start_time
            self.logger.info(f"Cleanup completed in {duration.total_seconds():.2f} seconds")
            
            return self.stats.errors == 0
            
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")
            self.stats.errors += 1
            return False
        finally:
            # Очистка ресурсов
            try:
                if self.db_session:
                    self.db_session.close()
                if self.db_engine:
                    self.db_engine.dispose()
            except Exception as e:
                self.logger.warning(f"Error closing database connection: {e}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Clean up orphaned images from MinIO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview only)
  python cleanup_orphaned_images.py
  
  # Live deletion
  python cleanup_orphaned_images.py --execute
  
  # Custom bucket with 20 threads
  python cleanup_orphaned_images.py --bucket images --execute --workers 20
  
  # Fast deletion with 50 threads
  python cleanup_orphaned_images.py --execute --workers 50
        """
    )
    
    parser.add_argument(
        "--bucket",
        default="uploads",
        help="MinIO bucket name (default: uploads)"
    )
    
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete files (default: dry run)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of parallel threads (default: 10)"
    )
    
    args = parser.parse_args()
    
    # Настройка уровня логирования
    if args.verbose:
        logging.getLogger("minio_cleanup").setLevel(logging.DEBUG)
    
    # Запуск очистки
    dry_run = not args.execute
    
    if dry_run:
        print("🔍 RUNNING IN DRY RUN MODE - NO FILES WILL BE DELETED")
        print("   Use --execute flag to actually delete files")
        print()
    else:
        print("⚠️  LIVE MODE - FILES WILL BE PERMANENTLY DELETED")
        print("   Press Ctrl+C to cancel...")
        print()
    
    try:
        with MinIOCleanupService(
            bucket_name=args.bucket,
            dry_run=dry_run,
            max_workers=args.workers
        ) as cleanup_service:
            success = cleanup_service.cleanup()
            
            if success:
                print("\n✅ Cleanup completed successfully")
                sys.exit(0)
            else:
                print("\n❌ Cleanup completed with errors")
                sys.exit(1)
                
    except KeyboardInterrupt:
        print("\n\n⚠️  Cleanup cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
