import httpx
from typing import Union, Dict

from fastapi import HTTPException
from httpx import Response

from app.RateLimitedHTTPClient import RateLimitedHTTPClient
from app.core.config import logger
from app.utils.telegram_logger import log_error_to_telegram
import asyncio


async def get_last_vehicles_data():
    url = "http://195.93.152.69:8667/vehicles/?skip=0&limit=100"
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
        try:
            await log_error_to_telegram(
                error=e,
                request=None,
                user=None,
                additional_context={
                    "action": "send_command_to_terminal",
                    "vehicle_id": vehicle_id,
                    "command": command,
                    "retries": retries
                }
            )
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {command}, {e}")


def get_vehicle_id_by_imei(imei: str) -> int:
    """Возвращает vehicle_id для конкретного IMEI"""
    imei_to_vehicle_id = {
        "860803068139548": 800283232,  # Hongqi
        "860803068143045": 800212421,  # Mercedes
        "860803068146253": 800339176   # Hyundai Tucson
    }
    vehicle_id = imei_to_vehicle_id.get(imei)
    if vehicle_id is None:
        raise HTTPException(status_code=404, detail=f"vehicle_id не найден для IMEI {imei}")
    return vehicle_id


def get_commands_by_imei(imei: str) -> dict:
    """Возвращает команды для конкретного IMEI"""
    commands_map = {
        "860803068139548": {  # Hongqi - vehicle_id 800283232
            "open": "chat OPEN|chat OPEN|chat OPEN",
            "close": "chat CLOSE|chat CLOSE|chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068143045": {  # Mercedes - vehicle_id 800212421
            "open": "OUTPUT3 1|chat OPEN|OUTPUT3 0",
            "close": "chat BUZZ|chat CLOSE|chat CLOSE|chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0|OUTPUT3 0",
            "lock_engine": "chat LOCK|OUTPUT0 1",
            "unlock_engine": "chat UNLOCK|OUTPUT0 0"
        },
        "860803068146253": {  # Hyundai Tucson - vehicle_id 800339176
            "open": "chat OPEN",
            "close": "chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        }
    }
    commands = commands_map.get(imei)
    if not commands:
        raise HTTPException(status_code=400, detail=f"Команды не найдены для IMEI {imei}")
    return commands


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


async def execute_gps_sequence(imei: str, token: str, sequence_type: str) -> Dict:
    """
    Универсальная функция для выполнения GPS команд по этапам
    
    :param imei: IMEI автомобиля
    :param token: Токен авторизации
    :param sequence_type: Тип последовательности ('selfie_exterior', 'interior', 'start')
    :return: Результат выполнения команд
    """
    commands = get_commands_by_imei(imei)
    if not commands:
        return {"success": False, "error": f"Команды для IMEI {imei} не найдены"}
    
    results = {"success": True, "executed_commands": [], "errors": []}
    
    try:
        if sequence_type == "selfie_exterior":
            # Этап 1: Селфи + кузов
            # 1. Открыть замки
            # 2. Выдать ключ  
            # 3. Открыть замки
            # 4. Забрать ключ
            
            # 1. Открыть замки
            try:
                open_cmd = commands.get("open", "")
                if open_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, open_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "open_locks", "result": result})
                    logger.info(f"Замки автомобиля {imei} открыты")
                    await asyncio.sleep(2)  # Пауза между командами
            except Exception as e:
                error_msg = f"Ошибка открытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Выдать ключ
            try:
                give_key_cmd = commands.get("give_key", "")
                if give_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, give_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "give_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} выдан")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка выдачи ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 3. Снова открыть замки
            try:
                open_cmd = commands.get("open", "")
                if open_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, open_cmd, token)
                    results["executed_commands"].append({"step": 3, "action": "open_locks_again", "result": result})
                    logger.info(f"Замки автомобиля {imei} открыты повторно")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка повторного открытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 4. Забрать ключ
            try:
                take_key_cmd = commands.get("take_key", "")
                if take_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, take_key_cmd, token)
                    results["executed_commands"].append({"step": 4, "action": "take_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} забран")
            except Exception as e:
                error_msg = f"Ошибка забора ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "interior":
            # Этап 2: Салон
            # 1. Разблокировать двигатель
            # 2. Выдать ключ
            
            # 1. Разблокировать двигатель
            try:
                unlock_engine_cmd = commands.get("unlock_engine", "")
                if unlock_engine_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, unlock_engine_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "unlock_engine", "result": result})
                    logger.info(f"Двигатель автомобиля {imei} разблокирован")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка разблокировки двигателя: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Выдать ключ
            try:
                give_key_cmd = commands.get("give_key", "")
                if give_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, give_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "give_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} выдан")
            except Exception as e:
                error_msg = f"Ошибка выдачи ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "start":
            # Этап 3: Старт
            # 1. Разблокировать двигатель
            
            # 1. Разблокировать двигатель
            try:
                unlock_engine_cmd = commands.get("unlock_engine", "")
                if unlock_engine_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, unlock_engine_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "unlock_engine", "result": result})
                    logger.info(f"Двигатель автомобиля {imei} разблокирован при старте")
            except Exception as e:
                error_msg = f"Ошибка разблокировки двигателя при старте: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "complete_selfie_interior":
            # Этап 4: Завершение - селфи + салон
            # 1. Заблокировать двигатель
            # 2. Забрать ключ
            # 3. Закрыть замки
            
            # 1. Заблокировать двигатель
            try:
                lock_engine_cmd = commands.get("lock_engine", "")
                if lock_engine_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, lock_engine_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": result})
                    logger.info(f"Двигатель автомобиля {imei} заблокирован")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка блокировки двигателя: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Забрать ключ
            try:
                take_key_cmd = commands.get("take_key", "")
                if take_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, take_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "take_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} забран")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка забора ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 3. Закрыть замки
            try:
                close_cmd = commands.get("close", "")
                if close_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, close_cmd, token)
                    results["executed_commands"].append({"step": 3, "action": "close_locks", "result": result})
                    logger.info(f"Замки автомобиля {imei} закрыты")
            except Exception as e:
                error_msg = f"Ошибка закрытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "complete_exterior":
            # Этап 5: Завершение - кузов
            # 1. Заблокировать двигатель
            # 2. Забрать ключ
            # 3. Закрыть замки
            
            # 1. Заблокировать двигатель
            try:
                lock_engine_cmd = commands.get("lock_engine", "")
                if lock_engine_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, lock_engine_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": result})
                    logger.info(f"Двигатель автомобиля {imei} заблокирован")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка блокировки двигателя: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Забрать ключ
            try:
                take_key_cmd = commands.get("take_key", "")
                if take_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, take_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "take_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} забран")
                    await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка забора ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 3. Закрыть замки
            try:
                close_cmd = commands.get("close", "")
                if close_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, close_cmd, token)
                    results["executed_commands"].append({"step": 3, "action": "close_locks", "result": result})
                    logger.info(f"Замки автомобиля {imei} закрыты")
            except Exception as e:
                error_msg = f"Ошибка закрытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "final_lock":
            # Этап 6: Окончательная блокировка
            # 1. Заблокировать двигатель
            
            # 1. Заблокировать двигатель
            try:
                lock_engine_cmd = commands.get("lock_engine", "")
                if lock_engine_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, lock_engine_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": result})
                    logger.info(f"Двигатель автомобиля {imei} окончательно заблокирован")
            except Exception as e:
                error_msg = f"Ошибка окончательной блокировки двигателя: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
        else:
            results["success"] = False
            results["error"] = f"Неизвестный тип последовательности: {sequence_type}"
            
    except Exception as e:
        error_msg = f"Общая ошибка выполнения GPS последовательности: {e}"
        results["errors"].append(error_msg)
        results["success"] = False
        logger.error(error_msg)
    
    return results