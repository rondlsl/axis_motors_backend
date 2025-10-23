import httpx
from typing import Union, Dict

from fastapi import HTTPException
from httpx import Response

from app.RateLimitedHTTPClient import RateLimitedHTTPClient
from app.core.config import logger


async def get_last_vehicles_data():
    url = "http://195.93.152.69:8666/vehicles/?skip=0&limit=100"
    headers = {"accept": "application/json"}

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_command_to_terminal(
        vehicle_id: int,
        command: str,
        token: str,
        retries: int = 3,
        id_template: Union[int, None] = None
) -> Dict:
    """
    Асинхронная функция для отправки команды на терминал с обработкой ошибок.

    :param vehicle_id: ID транспортного средства.
    :param command: Команда для отправки.
    :param token: Токен авторизации.
    :param retries: Количество попыток отправки.
    :param id_template: ID шаблона команды (если есть).
    :return: Словарь с command_id.
    """
    url = "https://regions.glonasssoft.ru/api/v3/Vehicles/cmd/create"
    headers = {
        "X-Auth": token,
        "Content-Type": "application/json"
    }

    payload = {
        "id": vehicle_id,
        "command": command,
        "retries": retries,
        "idTemplate": id_template
    }

    client = RateLimitedHTTPClient.get_instance()

    try:
        response: Response = await client.send_request("POST", url, headers=headers, json=payload)
        response.raise_for_status()
        command_id = response.text.strip('"')
        return {"command_id": command_id}

    except Exception as e:
        logger.error(f"Ошибка отправки команды для {vehicle_id}, {command}, {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {command}, {e}")


def get_vehicle_id_by_imei(imei: str) -> int:
    """Возвращает vehicle_id для конкретного IMEI"""
    imei_to_vehicle_id = {
        "860803068139548": 800283232,  # Hongqi
        "860803068143045": 800212421,  # Mercedes
        "866011056063951": 800153076   # HAVAL
    }
    return imei_to_vehicle_id.get(imei, 800153076)  # Дефолтный vehicle_id


def get_commands_by_imei(imei: str) -> dict:
    """Возвращает команды для конкретного IMEI"""
    commands_map = {
        "860803068139548": {  # Hongqi - vehicle_id 800283232
            "open": "chat OPEN|chat OPEN|chat OPEN",
            "close": "chat CLOSE|chat CLOSE|chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "chat LOCK",
            "unlock_engine": "chat UNLOCK|OUTPUT0 0"
        },
        "860803068143045": {  # Mercedes - vehicle_id 800212421
            "open": "OUTPUT3 1|chat OPEN|OUTPUT3 0",
            "close": "chat BUZZ|chat CLOSE|chat CLOSE|chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0|OUTPUT3 0",
            "lock_engine": "chat LOCK|OUTPUT0 1",
            "unlock_engine": "chat UNLOCK|OUTPUT0 0"
        },
        "866011056063951": {  # HAVAL - vehicle_id 800153076
            "open": "*!CEVT 1",
            "close": "*!CEVT 2",
            "give_key": "*!2Y",
            "take_key": "*!2N",
            "lock_engine": "*!1Y",
            "unlock_engine": "*!1N"
        }
    }
    return commands_map.get(imei, {
        "open": "*!CEVT 1",
        "close": "*!CEVT 2",
        "give_key": "*!2Y",
        "take_key": "*!2N",
        "lock_engine": "*!1Y",
        "unlock_engine": "*!1N"
    })


async def send_lock_engine(imei: str, token: str, retries: int = 1) -> dict:
    """Отправляет команду блокировки двигателя"""
    commands = get_commands_by_imei(imei)
    command = commands.get("lock_engine")
    if not command:
        raise HTTPException(status_code=400, detail=f"Команда блокировки двигателя не найдена для IMEI {imei}")
    
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, command, token, retries)


async def send_unlock_engine(imei: str, token: str, retries: int = 1) -> dict:
    """Отправляет команду разблокировки двигателя"""
    commands = get_commands_by_imei(imei)
    command = commands.get("unlock_engine")
    if not command:
        raise HTTPException(status_code=400, detail=f"Команда разблокировки двигателя не найдена для IMEI {imei}")
    
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, command, token, retries)


async def send_open(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["open"], token, retries)


async def send_close(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["close"], token, retries)


async def send_give_key(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["give_key"], token, retries)


async def send_take_key(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["take_key"], token, retries)


async def send_lock_engine(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["lock_engine"], token, retries)


async def send_unlock_engine(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["unlock_engine"], token, retries)


async def auto_lock_vehicle_after_rental(imei: str, token: str) -> dict:
    """
    Автоматически блокирует замки, двигатель и забирает ключ после завершения аренды.
    Вызывается после успешной загрузки фото салона/сэлфи.
    """
    results = {
        "close_doors": None,
        "lock_engine": None,
        "take_key": None,
        "errors": []
    }
    
    try:
        # 1. Закрыть замки
        try:
            results["close_doors"] = await send_close(imei, token)
            logger.info(f"Замки автомобиля {imei} заблокированы")
        except Exception as e:
            error_msg = f"Ошибка блокировки замков: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
        
        # 2. Заблокировать двигатель
        try:
            results["lock_engine"] = await send_lock_engine(imei, token)
            logger.info(f"Двигатель автомобиля {imei} заблокирован")
        except Exception as e:
            error_msg = f"Ошибка блокировки двигателя: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
        
        # 3. Забрать ключ
        try:
            results["take_key"] = await send_take_key(imei, token)
            logger.info(f"Ключ автомобиля {imei} забран")
        except Exception as e:
            error_msg = f"Ошибка забора ключа: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
            
    except Exception as e:
        error_msg = f"Общая ошибка автоматической блокировки: {e}"
        results["errors"].append(error_msg)
        logger.error(error_msg)
    
    return results