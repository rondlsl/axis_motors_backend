#!/usr/bin/env python3
"""
Скрипт для автоматического планирования резервных копий базы данных
Использует APScheduler для создания расписания бэкапов
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backup_scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BackupScheduler:
    def __init__(self):
        self.scheduler = BlockingScheduler()
        self.backup_script = os.path.join(os.path.dirname(__file__), 'backup_database.sh')
        
    def create_daily_backup(self):
        """Создает ежедневный полный бэкап в 02:00"""
        logger.info("Запуск ежедневного полного бэкапа")
        try:
            result = subprocess.run(
                [self.backup_script, 'full', 'daily'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Ежедневный бэкап завершен: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при ежедневном бэкапе: {e.stderr}")
    
    def create_weekly_backup(self):
        """Создает еженедельный полный бэкап в воскресенье в 01:00"""
        logger.info("Запуск еженедельного полного бэкапа")
        try:
            result = subprocess.run(
                [self.backup_script, 'full', 'weekly'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Еженедельный бэкап завершен: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при еженедельном бэкапе: {e.stderr}")
    
    def create_monthly_backup(self):
        """Создает ежемесячный полный бэкап 1 числа в 00:00"""
        logger.info("Запуск ежемесячного полного бэкапа")
        try:
            result = subprocess.run(
                [self.backup_script, 'full', 'monthly'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Ежемесячный бэкап завершен: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при ежемесячном бэкапе: {e.stderr}")
    
    def create_incremental_backup(self):
        """Создает инкрементальный бэкап каждый час"""
        logger.info("Запуск инкрементального бэкапа")
        try:
            result = subprocess.run(
                [self.backup_script, 'incremental', 'daily'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Инкрементальный бэкап завершен: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при инкрементальном бэкапе: {e.stderr}")
    
    def cleanup_old_backups(self):
        """Очистка старых бэкапов"""
        logger.info("Запуск очистки старых бэкапов")
        try:
            result = subprocess.run(
                [self.backup_script, 'cleanup'],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Очистка завершена: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка при очистке: {e.stderr}")
    
    def setup_schedule(self):
        """Настройка расписания бэкапов"""
        logger.info("Настройка расписания бэкапов")
        
        # Ежедневный полный бэкап в 02:00
        self.scheduler.add_job(
            func=self.create_daily_backup,
            trigger=CronTrigger(hour=2, minute=0),
            id='daily_backup',
            name='Ежедневный полный бэкап',
            replace_existing=True
        )
        
        # Еженедельный полный бэкап в воскресенье в 01:00
        self.scheduler.add_job(
            func=self.create_weekly_backup,
            trigger=CronTrigger(day_of_week=6, hour=1, minute=0),
            id='weekly_backup',
            name='Еженедельный полный бэкап',
            replace_existing=True
        )
        
        # Ежемесячный полный бэкап 1 числа в 00:00
        self.scheduler.add_job(
            func=self.create_monthly_backup,
            trigger=CronTrigger(day=1, hour=0, minute=0),
            id='monthly_backup',
            name='Ежемесячный полный бэкап',
            replace_existing=True
        )
        
        # Инкрементальный бэкап каждый час
        # self.scheduler.add_job(
        #     func=self.create_incremental_backup,
        #     trigger=CronTrigger(minute=0),
        #     id='incremental_backup',
        #     name='Инкрементальный бэкап',
        #     replace_existing=True
        # )
        
        # Очистка старых бэкапов каждый день в 03:00
        self.scheduler.add_job(
            func=self.cleanup_old_backups,
            trigger=CronTrigger(hour=3, minute=0),
            id='cleanup_backups',
            name='Очистка старых бэкапов',
            replace_existing=True
        )
        
        logger.info("Расписание настроено:")
        logger.info("Ежедневный полный бэкап: 02:00")
        logger.info("Еженедельный полный бэкап: воскресенье 01:00")
        logger.info("Ежемесячный полный бэкап: 1 число 00:00")
        # logger.info("Инкрементальный бэкап: каждый час")
        logger.info("Очистка старых бэкапов: 03:00")
        # logger.info("Планировщик бэкапов отключен")
    
    def start(self):
        """Запуск планировщика"""
        logger.info("Запуск планировщика бэкапов")
        try:
            self.scheduler.start()
        except KeyboardInterrupt:
            logger.info("Планировщик остановлен пользователем")
            self.scheduler.shutdown()

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        scheduler = BackupScheduler()
        logger.info("Тестовый режим - создание бэкапа")
        scheduler.create_daily_backup()
    else:
        scheduler = BackupScheduler()
        scheduler.setup_schedule()
        scheduler.start()

if __name__ == '__main__':
    main()
