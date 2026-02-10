"""
Сервис бэкапа базы данных PostgreSQL с сохранением в MinIO.
Поддерживает автоматические бэкапы через APScheduler и ручные бэкапы.
"""
import os
import subprocess
import logging
from datetime import datetime
from typing import Optional

from app.core.config import (
    DATABASE_URL,
    MINIO_BUCKET_BACKUPS,
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_USE_SSL,
)
from app.services.minio_service import get_minio_service
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class BackupService:
    """Сервис для создания и управления бэкапами БД."""

    def __init__(self):
        self.minio = get_minio_service()

    def _parse_database_url(self) -> dict:
        """Парсит DATABASE_URL в компоненты для pg_dump."""
        try:
            # DATABASE_URL формат: postgresql://user:password@host:port/dbname
            # или postgresql+psycopg2://user:password@host:port/dbname
            import re
            pattern = r'postgresql(\+psycopg2)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
            match = re.match(pattern, DATABASE_URL)
            if not match:
                raise ValueError("Invalid DATABASE_URL format")
            
            return {
                'user': match.group(2),
                'password': match.group(3),
                'host': match.group(4),
                'port': match.group(5),
                'dbname': match.group(6),
            }
        except Exception as e:
            logger.error(f"Failed to parse DATABASE_URL: {e}")
            raise

    def create_backup(self, backup_name: Optional[str] = None) -> Optional[str]:
        """
        Создать бэкап базы данных и сохранить в MinIO.
        
        Args:
            backup_name: Опциональное имя бэкапа. Если None, генерируется автоматически.
            
        Returns:
            Имя файла бэкапа в MinIO или None в случае ошибки.
        """
        try:
            if not backup_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"backup_{timestamp}.sql"
            
            # Парсим DATABASE_URL
            db_config = self._parse_database_url()
            
            # Формируем команду pg_dump (оптимизированная версия)
            pg_dump_cmd = [
                'pg_dump',
                f'--host={db_config["host"]}',
                f'--port={db_config["port"]}',
                f'--username={db_config["user"]}',
                f'--dbname={db_config["dbname"]}',
                '--no-password',
                '--quiet',  # Уменьшаем логирование для производительности
                '--clean',
                '--if-exists',
                '--create',
                '--format=custom',
                '--compress=9',  # Максимальная компрессия
                '--jobs=2',  # Используем 2 потока для параллельной работы
                f'--file=/tmp/{backup_name}'
            ]
            
            # Устанавливаем переменную окружения с паролем
            env = os.environ.copy()
            env['PGPASSWORD'] = db_config['password']
            
            logger.info(f"Starting database backup: {backup_name}")
            
            # Выполняем pg_dump
            result = subprocess.run(
                pg_dump_cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 минут таймаут
            )
            
            if result.returncode != 0:
                logger.error(f"pg_dump failed: {result.stderr}")
                return None
            
            # Загружаем бэкап в MinIO
            backup_path = f"/tmp/{backup_name}"
            object_name = f"database/{backup_name}"
            
            try:
                with open(backup_path, 'rb') as f:
                    file_size = os.path.getsize(backup_path)
                    logger.info(f"Uploading backup to MinIO: {object_name} ({file_size} bytes)")
                    
                    self.minio.client.put_object(
                        Bucket=MINIO_BUCKET_BACKUPS,
                        Key=object_name,
                        Body=f,
                        ContentLength=file_size,
                        ContentType='application/octet-stream'
                    )
                
                logger.info(f"Backup successfully uploaded: {object_name}")
                
                # Удаляем временный файл
                os.remove(backup_path)
                
                return object_name
                
            except Exception as e:
                logger.error(f"Failed to upload backup to MinIO: {e}")
                # Оставляем файл локально для анализа
                return backup_path
                
        except subprocess.TimeoutExpired:
            logger.error("Backup timeout after 5 minutes")
            return None
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return None

    def list_backups(self, limit: int = 50) -> list:
        try:
            objects = self.minio.client.list_objects_v2(
                Bucket=MINIO_BUCKET_BACKUPS,
                Prefix='database/',
                MaxKeys=1000
            )
            
            backups = []
            for obj in objects.get('Contents', []):
                if obj['Key'].endswith('.sql'):
                    backups.append({
                        'name': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'],
                        'etag': obj.get('ETag', '')
                    })
            
            # Сортируем по дате модификации (новые первые)
            backups.sort(key=lambda x: x['last_modified'], reverse=True)
            
            return backups[:limit]
            
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def restore_backup(self, backup_name: str) -> bool:
        """
        Восстановить базу данных из бэкапа.
        
        Args:
            backup_name: Имя файла бэкапа в MinIO
            
        Returns:
            True если восстановление успешно, иначе False
        """
        try:
            object_name = f"database/{backup_name}"
            local_path = f"/tmp/{backup_name}"
            
            # Скачиваем бэкап из MinIO
            logger.info(f"Downloading backup from MinIO: {object_name}")
            self.minio.client.download_file(
                Bucket=MINIO_BUCKET_BACKUPS,
                Key=object_name,
                Filename=local_path
            )
            
            # Парсим DATABASE_URL
            db_config = self._parse_database_url()
            
            # Формируем команду pg_restore
            pg_restore_cmd = [
                'pg_restore',
                f'--host={db_config["host"]}',
                f'--port={db_config["port"]}',
                f'--username={db_config["user"]}',
                f'--dbname={db_config["dbname"]}',
                '--no-password',
                '--verbose',
                '--clean',
                '--if-exists',
                '--create',
                local_path
            ]
            
            # Устанавливаем переменную окружения с паролем
            env = os.environ.copy()
            env['PGPASSWORD'] = db_config['password']
            
            logger.info(f"Starting database restore from: {backup_name}")
            
            # Выполняем pg_restore
            result = subprocess.run(
                pg_restore_cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=600  # 10 минут таймаут
            )
            
            # Удаляем временный файл
            os.remove(local_path)
            
            if result.returncode != 0:
                logger.error(f"pg_restore failed: {result.stderr}")
                return False
            
            logger.info(f"Database successfully restored from: {backup_name}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Restore timeout after 10 minutes")
            return False
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def delete_backup(self, backup_name: str) -> bool:
        """
        Удалить бэкап из MinIO.
        
        Args:
            backup_name: Имя файла бэкапа
            
        Returns:
            True если удаление успешно, иначе False
        """
        try:
            object_name = f"database/{backup_name}"
            self.minio.client.delete_object(
                Bucket=MINIO_BUCKET_BACKUPS,
                Key=object_name
            )
            logger.info(f"Backup deleted: {object_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup: {e}")
            return False

    def cleanup_old_backups(self, keep_count: int = 30) -> int:
        """
        Удалить старые бэкапы, оставив только последние N.
        
        Args:
            keep_count: Сколько последних бэкапов оставить
            
        Returns:
            Количество удаленных бэкапов
        """
        try:
            backups = self.list_backups(limit=1000)
            
            if len(backups) <= keep_count:
                return 0
            
            # Удаляем самые старые
            to_delete = backups[keep_count:]
            deleted_count = 0
            
            for backup in to_delete:
                backup_name = backup['name'].replace('database/', '')
                if self.delete_backup(backup_name):
                    deleted_count += 1
            
            logger.info(f"Cleaned up {deleted_count} old backups")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {e}")
            return 0


# Глобальный экземпляр сервиса
_backup_service: Optional[BackupService] = None


def get_backup_service() -> BackupService:
    """Получить экземпляр BackupService (singleton)."""
    global _backup_service
    if _backup_service is None:
        _backup_service = BackupService()
    return _backup_service


async def create_scheduled_backup():
    """Асинхронная функция для вызова из APScheduler."""
    import asyncio
    
    def run_backup_task():
        """Выполняет бэкап в отдельном потоке."""
        try:
            service = get_backup_service()
            backup_name = service.create_backup()
            if backup_name:
                logger.info(f"Scheduled backup created: {backup_name}")
                # Очистка старых бэкапов (оставляем последние 30)
                service.cleanup_old_backups(keep_count=30)
            else:
                logger.error("Scheduled backup failed")
        except Exception as e:
            logger.error(f"Scheduled backup error: {e}")
    
    # Запускаем бэкап в отдельном потоке, чтобы не блокировать event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_backup_task)
