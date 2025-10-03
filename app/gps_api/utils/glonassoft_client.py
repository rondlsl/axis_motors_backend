import httpx
from typing import Dict, Any, Optional
import logging

from app.core.config import GLONASSSOFT_USERNAME, GLONASSSOFT_PASSWORD

logger = logging.getLogger(__name__)


class GlonassoftClient:
    """Клиент для работы с API Глонассофт"""
    
    def __init__(self):
        self.base_url = "https://regions.glonasssoft.ru"
        self.token = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def authenticate(self) -> bool:
        """Аутентификация в системе Глонассофт"""
        try:
            auth_data = {
                "login": GLONASSSOFT_USERNAME,
                "password": GLONASSSOFT_PASSWORD
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/auth/login",
                json=auth_data
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("token")
                logger.info("Successfully authenticated with Glonassoft")
                return True
            else:
                logger.error(f"Authentication failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    async def get_vehicle_data(self, vehicle_imei: str) -> Optional[Dict[str, Any]]:
        """Получает данные о конкретном автомобиле по IMEI"""
        if not self.token:
            logger.info("No token, authenticating...")
            if not await self.authenticate():
                logger.error("Authentication failed")
                return None
        
        try:
            headers = {
                "X-Auth": self.token,
                "Content-Type": "application/json"
            }
            
            url = f"{self.base_url}/api/v2.0/monitoringVehicles/devicestatebyimei"
            params = {
                "imei": vehicle_imei,
                "timezone": 5
            }
            
            logger.info(f"Requesting telemetry from {url} with IMEI={vehicle_imei}")
            response = await self.client.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully received telemetry data for {vehicle_imei}")
                return data
            else:
                logger.error(f"Failed to get vehicle data for {vehicle_imei}: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting vehicle data for {vehicle_imei}: {e}")
            return None
    
    async def get_last_vehicles_data(self, vehicle_ids: list) -> Optional[list]:
        """Получает последние данные по нескольким автомобилям"""
        if not self.token:
            if not await self.authenticate():
                return None
        
        try:
            headers = {
                "X-Auth": self.token,
                "Content-Type": "application/json"
            }
            
            url = f"{self.base_url}/api/v3/vehicles/getlastdata"
            
            response = await self.client.post(url, json=vehicle_ids, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get last vehicles data: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting last vehicles data: {e}")
            return None
    
    async def close(self):
        """Закрывает HTTP клиент"""
        await self.client.aclose()


# Глобальный экземпляр клиента
glonassoft_client = GlonassoftClient()
