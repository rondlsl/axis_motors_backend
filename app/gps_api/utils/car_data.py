import httpx
import requests
from typing import List, Union, Dict

from fastapi import HTTPException
from httpx import Response

from app.RateLimitedHTTPClient import RateLimitedHTTPClient


async def get_last_vehicles_data():
    url = "http://195.49.210.50:8666/vehicles/?skip=0&limit=100"
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
        print(f"Ошибка при выполнении запроса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {command}")


async def send_open(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!CEVT 1", token, retries)


async def send_close(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!CEVT 2", token, retries)


async def send_give_key(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!2Y", token, retries)


async def send_take_key(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!2N", token, retries)


async def send_lock_engine(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!1Y", token, retries)


async def send_unlock_engine(vehicle_id: int, token: str, retries: int = 1) -> dict:
    return await send_command_to_terminal(vehicle_id, "*!1N", token, retries)
