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


def get_commands_by_vehicle_id(vehicle_id: int) -> dict:
    """Возвращает команды для конкретного vehicle_id"""
    commands_map = {
        800283232: {  # imei 869132074464026
            "open": "chat OPEN",
            "close": "chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "chat LOCK",
            "unlock_engine": "chat UNLOCK"
        },
        800212421: {  # imei 869132074567851
            "open": "chat OP|chat OPEN",
            "close": "chat CL|chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        800153076: {  # imei 866011056063951
            "open": "*!CEVT 1",
            "close": "*!CEVT 2",
            "give_key": "*!2Y",
            "take_key": "*!2N",
            "lock_engine": "*!1Y",
            "unlock_engine": "*!1N"
        }
    }
    return commands_map.get(vehicle_id, {
        "open": "*!CEVT 1",
        "close": "*!CEVT 2",
        "give_key": "*!2Y",
        "take_key": "*!2N",
        "lock_engine": "*!1Y",
        "unlock_engine": "*!1N"
    })


async def send_open(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["open"], token, retries)


async def send_close(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["close"], token, retries)


async def send_give_key(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["give_key"], token, retries)


async def send_take_key(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["take_key"], token, retries)


async def send_lock_engine(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["lock_engine"], token, retries)


async def send_unlock_engine(vehicle_id: int, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_vehicle_id(vehicle_id)
    return await send_command_to_terminal(vehicle_id, commands["unlock_engine"], token, retries)
