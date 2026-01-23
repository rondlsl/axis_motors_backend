"""
MinIO Service для работы с объектным хранилищем S3-совместимым.
"""
import os
import uuid
import time
from typing import Optional, List
from io import BytesIO
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException

from app.core.config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET_UPLOADS,
    MINIO_BUCKET_BACKUPS,
    MINIO_PUBLIC_URL,
    MINIO_USE_SSL
)

logger = logging.getLogger(__name__)


class MinIOService:
    """Сервис для работы с MinIO/S3"""
    
    _instance: Optional['MinIOService'] = None
    _client: Optional[boto3.client] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            self._initialize_client()
    
    def _initialize_client(self):
        """Инициализация клиента S3/MinIO"""
        try:
            self._client = boto3.client(
                's3',
                endpoint_url=MINIO_ENDPOINT,
                aws_access_key_id=MINIO_ACCESS_KEY,
                aws_secret_access_key=MINIO_SECRET_KEY,
                config=boto3.session.Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'}
                )
            )
            logger.info(f"✅ MinIO client initialized: {MINIO_ENDPOINT}")
            
            # Проверяем/создаём bucket'ы
            self._ensure_buckets()
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize MinIO client: {e}")
            raise
    
    def _ensure_buckets(self):
        """Создание bucket'ов если они не существуют"""
        buckets = [MINIO_BUCKET_UPLOADS, MINIO_BUCKET_BACKUPS]
        
        for bucket in buckets:
            try:
                self._client.head_bucket(Bucket=bucket)
                logger.info(f"✅ Bucket '{bucket}' exists")
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == '404':
                    try:
                        self._client.create_bucket(Bucket=bucket)
                        logger.info(f"✅ Bucket '{bucket}' created")
                    except Exception as create_error:
                        logger.error(f"❌ Failed to create bucket '{bucket}': {create_error}")
                else:
                    logger.warning(f"⚠️ Cannot access bucket '{bucket}': {e}")
    
    @property
    def client(self):
        """Получить клиент S3"""
        if self._client is None:
            self._initialize_client()
        return self._client
    
    async def upload_file(
        self,
        file: UploadFile,
        object_id: uuid.UUID,
        folder: str,
        bucket: str = None
    ) -> str:
        """
        Загрузить файл в MinIO.
        
        Args:
            file: FastAPI UploadFile объект
            object_id: UUID для генерации уникального имени (user_id, rental_id, etc.)
            folder: Папка в bucket'е (например: "documents", "cars/ABC123", "rents/uuid/before")
            bucket: Имя bucket'а (по умолчанию MINIO_BUCKET_UPLOADS)
            
        Returns:
            str: Публичный URL файла
        """
        start_time = time.time()
        bucket = bucket or MINIO_BUCKET_UPLOADS
        
        logger.info(f"[MINIO_UPLOAD] START: filename={file.filename}, object_id={object_id}, folder={folder}")
        
        # Генерируем уникальное имя файла
        file_extension = os.path.splitext(file.filename or "file")[1]
        unique_filename = f"{object_id}_{uuid.uuid4()}{file_extension}"
        
        # Полный путь объекта (ключ)
        object_key = f"{folder.strip('/')}/{unique_filename}"
        
        try:
            # Читаем содержимое файла
            read_start = time.time()
            content = await file.read()
            logger.info(f"[MINIO_UPLOAD] File read took {time.time() - read_start:.3f}s, size={len(content)} bytes")
            
            # Определяем content type
            content_type = file.content_type or 'application/octet-stream'
            
            # Загружаем в MinIO
            upload_start = time.time()
            self.client.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=BytesIO(content),
                ContentType=content_type,
                ContentLength=len(content)
            )
            logger.info(f"[MINIO_UPLOAD] Upload took {time.time() - upload_start:.3f}s")
            
            # Формируем публичный URL
            public_url = f"{MINIO_PUBLIC_URL}/{bucket}/{object_key}"
            
            total_duration = time.time() - start_time
            logger.info(f"[MINIO_UPLOAD] TOTAL took {total_duration:.3f}s, URL: {public_url}")
            
            return public_url
            
        except Exception as e:
            logger.error(f"[MINIO_UPLOAD] ERROR: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка загрузки файла в хранилище: {str(e)}"
            )
    
    def upload_file_sync(
        self,
        content: bytes,
        filename: str,
        folder: str,
        content_type: str = 'application/octet-stream',
        bucket: str = None
    ) -> str:
        """
        Синхронная загрузка файла в MinIO.
        
        Args:
            content: Байты файла
            filename: Имя файла
            folder: Папка в bucket'е
            content_type: MIME тип
            bucket: Имя bucket'а
            
        Returns:
            str: Публичный URL файла
        """
        bucket = bucket or MINIO_BUCKET_UPLOADS
        
        # Полный путь объекта (ключ)
        object_key = f"{folder.strip('/')}/{filename}"
        
        try:
            self.client.put_object(
                Bucket=bucket,
                Key=object_key,
                Body=BytesIO(content),
                ContentType=content_type,
                ContentLength=len(content)
            )
            
            # Формируем публичный URL
            return f"{MINIO_PUBLIC_URL}/{bucket}/{object_key}"
            
        except Exception as e:
            logger.error(f"[MINIO_UPLOAD_SYNC] ERROR: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка загрузки файла в хранилище: {str(e)}"
            )
    
    def delete_file(self, url: str) -> bool:
        """
        Удалить файл из MinIO по URL.
        
        Args:
            url: Публичный URL файла
            
        Returns:
            bool: True если успешно удалён
        """
        try:
            # Извлекаем bucket и key из URL
            # URL формат: https://msmain.azvmotors.kz/uploads/folder/file.jpg
            url_without_protocol = url.replace("https://", "").replace("http://", "")
            parts = url_without_protocol.split("/", 1)
            
            if len(parts) < 2:
                logger.warning(f"[MINIO_DELETE] Invalid URL format: {url}")
                return False
            
            path = parts[1]  # uploads/folder/file.jpg
            path_parts = path.split("/", 1)
            
            if len(path_parts) < 2:
                logger.warning(f"[MINIO_DELETE] Cannot extract bucket/key from: {url}")
                return False
            
            bucket = path_parts[0]
            object_key = path_parts[1]
            
            self.client.delete_object(Bucket=bucket, Key=object_key)
            logger.info(f"[MINIO_DELETE] Deleted: {bucket}/{object_key}")
            return True
            
        except Exception as e:
            logger.error(f"[MINIO_DELETE] ERROR deleting {url}: {e}")
            return False
    
    def delete_files(self, urls: List[str]) -> int:
        """
        Удалить несколько файлов из MinIO.
        
        Args:
            urls: Список URL файлов
            
        Returns:
            int: Количество успешно удалённых файлов
        """
        deleted_count = 0
        for url in urls:
            if self.delete_file(url):
                deleted_count += 1
        return deleted_count
    
    def delete_folder(self, folder: str, bucket: str = None) -> int:
        """
        Удалить все файлы в папке.
        
        Args:
            folder: Путь к папке
            bucket: Имя bucket'а
            
        Returns:
            int: Количество удалённых файлов
        """
        bucket = bucket or MINIO_BUCKET_UPLOADS
        
        try:
            # Получаем список объектов в папке
            response = self.client.list_objects_v2(
                Bucket=bucket,
                Prefix=folder.strip('/') + '/'
            )
            
            deleted_count = 0
            objects = response.get('Contents', [])
            
            if not objects:
                logger.info(f"[MINIO_DELETE_FOLDER] No objects found in {bucket}/{folder}")
                return 0
            
            # Удаляем объекты пакетно
            delete_objects = [{'Key': obj['Key']} for obj in objects]
            
            self.client.delete_objects(
                Bucket=bucket,
                Delete={'Objects': delete_objects}
            )
            
            deleted_count = len(delete_objects)
            logger.info(f"[MINIO_DELETE_FOLDER] Deleted {deleted_count} objects from {bucket}/{folder}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"[MINIO_DELETE_FOLDER] ERROR: {e}")
            return 0
    
    def get_file(self, url: str) -> Optional[bytes]:
        """
        Получить содержимое файла по URL.
        
        Args:
            url: Публичный URL файла
            
        Returns:
            bytes: Содержимое файла или None
        """
        try:
            # Извлекаем bucket и key из URL
            url_without_protocol = url.replace("https://", "").replace("http://", "")
            parts = url_without_protocol.split("/", 1)
            
            if len(parts) < 2:
                return None
            
            path = parts[1]
            path_parts = path.split("/", 1)
            
            if len(path_parts) < 2:
                return None
            
            bucket = path_parts[0]
            object_key = path_parts[1]
            
            response = self.client.get_object(Bucket=bucket, Key=object_key)
            return response['Body'].read()
            
        except Exception as e:
            logger.error(f"[MINIO_GET] ERROR getting {url}: {e}")
            return None
    
    def file_exists(self, url: str) -> bool:
        """
        Проверить существует ли файл.
        
        Args:
            url: Публичный URL файла
            
        Returns:
            bool: True если файл существует
        """
        try:
            url_without_protocol = url.replace("https://", "").replace("http://", "")
            parts = url_without_protocol.split("/", 1)
            
            if len(parts) < 2:
                return False
            
            path = parts[1]
            path_parts = path.split("/", 1)
            
            if len(path_parts) < 2:
                return False
            
            bucket = path_parts[0]
            object_key = path_parts[1]
            
            self.client.head_object(Bucket=bucket, Key=object_key)
            return True
            
        except ClientError:
            return False
    
    def list_files(self, folder: str, bucket: str = None) -> List[str]:
        """
        Получить список файлов в папке.
        
        Args:
            folder: Путь к папке
            bucket: Имя bucket'а
            
        Returns:
            List[str]: Список URL файлов
        """
        bucket = bucket or MINIO_BUCKET_UPLOADS
        
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket,
                Prefix=folder.strip('/') + '/'
            )
            
            urls = []
            for obj in response.get('Contents', []):
                urls.append(f"{MINIO_PUBLIC_URL}/{bucket}/{obj['Key']}")
            
            return urls
            
        except Exception as e:
            logger.error(f"[MINIO_LIST] ERROR: {e}")
            return []


# Глобальный экземпляр сервиса
_minio_service: Optional[MinIOService] = None


def get_minio_service() -> MinIOService:
    """Получить экземпляр MinIO сервиса (singleton)"""
    global _minio_service
    if _minio_service is None:
        _minio_service = MinIOService()
    return _minio_service


# === Утилиты для совместимости с существующим кодом ===

async def save_file_to_minio(
    file: UploadFile,
    object_id: uuid.UUID,
    folder: str
) -> str:
    """
    Совместимая функция для сохранения файла в MinIO.
    Заменяет старую save_file() функцию.
    
    Args:
        file: FastAPI UploadFile объект
        object_id: UUID (user_id, rental_id, etc.)
        folder: Папка для сохранения (например: "documents", "rents/{rental_id}/before")
        
    Returns:
        str: Публичный URL файла
    """
    minio = get_minio_service()
    return await minio.upload_file(file, object_id, folder)


def delete_minio_files(file_urls: List[str]) -> None:
    """
    Удалить файлы из MinIO.
    Заменяет старую delete_uploaded_files() функцию.
    
    Args:
        file_urls: Список URL файлов для удаления
    """
    minio = get_minio_service()
    deleted = minio.delete_files(file_urls)
    logger.info(f"[MINIO_DELETE] Deleted {deleted} out of {len(file_urls)} files")

