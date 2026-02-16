import httpx
from typing import Union, Dict

from fastapi import HTTPException
from httpx import Response

from app.RateLimitedHTTPClient import RateLimitedHTTPClient
from app.core.logging_config import get_logger
from app.utils.telegram_logger import log_error_to_telegram

logger = get_logger(__name__)
import asyncio

LOCK_ENGINE_DISABLED_IMEIS = {"860803068143045", "860803068139548", "860803068133152"}  # CLA45s, Hongqi, Mercedes W222
LOCK_ENGINE_DISABLED_VEHICLE_IDS = {800212421, 800283232, 800412252}  # CLA45s, Hongqi, Mercedes W222


async def get_last_vehicles_data():
    from app.core.config import VEHICLES_API_URL
    url = f"{VEHICLES_API_URL}/vehicles/?skip=0&limit=100"
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
    import time
    cmd_start = time.time()
    logger.info(
        "[GPS CMD] send_command_to_terminal: vehicle_id=%s, command=%s, retries=%s, id_template=%s, token_set=%s",
        vehicle_id, command, retries, id_template, token is not None and len(str(token)) > 0
    )
    if not token:
        logger.error(
            "[GPS CMD] No auth token for vehicle_id=%s, command='%s' — Glonass auth failed or not requested",
            vehicle_id, command
        )
        raise HTTPException(
            status_code=503,
            detail="Токен авторизации Glonass недоступен. Повторите попытку позже."
        )
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
    logger.debug("[GPS CMD] POST %s payload=%s", url, payload)
    client = RateLimitedHTTPClient.get_instance()

    try:
        response: Response = await client.send_request("POST", url, headers=headers, json=payload)
        cmd_after_request = time.time() - cmd_start
        logger.info(
            "[GPS CMD] Response received in %.2fs: status=%s, body_len=%s",
            cmd_after_request, response.status_code, len(response.text) if response.text else 0
        )
        response.raise_for_status()
        command_id = response.text.strip('"')
        cmd_duration = time.time() - cmd_start
        logger.info(
            "[GPS CMD] Command '%s' to vehicle_id=%s completed in %.2fs, command_id=%s",
            command, vehicle_id, cmd_duration, command_id
        )
        return {"command_id": command_id}

    except Exception as e:
        cmd_duration = time.time() - cmd_start
        logger.warning(
            "[GPS CMD] Command '%s' to vehicle_id=%s FAILED after %.2fs: type=%s, error=%s",
            command, vehicle_id, cmd_duration, type(e).__name__, e
        )
        logger.error(
            "Ошибка отправки команды: vehicle_id=%s, command=%s, retries=%s — %s",
            vehicle_id, command, retries, e,
            exc_info=True
        )
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
        "860803068143045": 800212421,  # Mercedes CLA45s
        "860803068146253": 800339176,  # Hyundai Tucson
        "860803068155890": 800298270,  # Mercedes G63
        "860803068155916": 800370225,  # BYD Han EV
        "860803068139613": 800406786,  # Maserati Ghibli
        "860803068151071": 800408106,  # Toyota Camry
        "860803068151105": 800409927,  # Range Rover Sport Supercharged
        "860803068133657": 800410477,  # Li L7 Ultra
        "860803068133152": 800412252,  # Mercedes W222 (323BME02)
        "860803068155965": 800413326,  # Lexus GX460
        "860803068133343": 800415861,  # BMW G30
        "860803068156161": 800415862,  # 058BFF02 (AZV-MOTORS) — при необходимости уточните vehicle_id в системе
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
        "860803068143045": {  # Mercedes CLA45s - vehicle_id 800212421
            "open": "chat OPEN|OUTPUT1 1|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "close": "chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068146253": {  # Hyundai Tucson - vehicle_id 800339176
            "open": "chat OPEN",
            "close": "chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068155890": {  # Mercedes G63 - vehicle_id 800298270
            "open": "chat OPEN|OUTPUT1 1|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "close": "chat CLOSE",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068155916": {  # BYD Han EV - vehicle_id 800370225
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0OUTPUT3 0|OUTPUT1 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068139613": {  # Maserati Ghibli - vehicle_id 800406786
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068151071": {  # Toyota Camry - vehicle_id 800408106
            "open": "OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0",
            "close": "OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068151105": {  # Range Rover Sport Supercharged - vehicle_id 800409927
            # ВАЖНО: open и close нужно отправлять 2 раза! С 1 раза не срабатывает
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT3 1|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT3 0||OUTPUT2 0",
            "close": "OUTPUT1 1|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT2 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT2 0|OUTPUT2 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0",
            "requires_double_send": True  # Флаг для двойной отправки open/close
        },
        "860803068133657": {  # Li L7 Ultra - vehicle_id 800410477
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0",
            "requires_double_send": True  # Закрыть отправляется 2 раза
        },
        "860803068133152": {  # Mercedes W222 - vehicle_id 800412252
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "give_key": "OUTPUT1 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068155965": {  # Lexus GX460 - vehicle_id 800413326
            "open": "OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0",
            "close": "OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068133343": {  # BMW G30 - vehicle_id 800415861
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068156161": {  # 058BFF02 (AZV-MOTORS)
            "open": "OUTPUT3 1|OUTPUT2 0|OUTPUT3 0",
            "close": "OUTPUT2 1|OUTPUT3 0|OUTPUT2 0",
            "give_key": "OUTPUT1 1",
            "take_key": "OUTPUT1 0",
            "lock_engine": "OUTPUT0 1",
            "unlock_engine": "OUTPUT0 0"
        },
        "860803068133152": {  # 323BME02 (AZV-MOTORS)
            "open": "OUTPUT1 1|OUTPUT3 0|OUTPUT2 1|OUTPUT3 0|OUTPUT3 0|OUTPUT3 0|OUTPUT2 0|OUTPUT1 0",
            "close": "OUTPUT1 1|OUTPUT2 0|OUTPUT3 1|OUTPUT2 0|OUTPUT2 0|OUTPUT2 0|OUTPUT3 0|OUTPUT1 0",
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
    result = await send_command_to_terminal(vehicle_id, commands["open"], token, retries)
    # Для некоторых авто (Range Rover) нужно отправлять команду 2 раза
    if commands.get("requires_double_send"):
        logger.info(f"Отправка повторной команды open для IMEI {imei} (requires_double_send)")
        await asyncio.sleep(1)  # Небольшая пауза между командами
        result = await send_command_to_terminal(vehicle_id, commands["open"], token, retries)
    return result


async def send_close(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    result = await send_command_to_terminal(vehicle_id, commands["close"], token, retries)
    # Для некоторых авто (Range Rover) нужно отправлять команду 2 раза
    if commands.get("requires_double_send"):
        logger.info(f"Отправка повторной команды close для IMEI {imei} (requires_double_send)")
        await asyncio.sleep(1)  # Небольшая пауза между командами
        result = await send_command_to_terminal(vehicle_id, commands["close"], token, retries)
    return result


async def send_give_key(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["give_key"], token, retries)


async def send_take_key(imei: str, token: str, retries: int = 1) -> dict:
    commands = get_commands_by_imei(imei)
    vehicle_id = get_vehicle_id_by_imei(imei)
    return await send_command_to_terminal(vehicle_id, commands["take_key"], token, retries)


async def send_lock_engine(imei: str, token: str, retries: int = 1) -> dict:
    if imei in LOCK_ENGINE_DISABLED_IMEIS:
        logger.info(f"Lock engine command skipped for IMEI {imei}")
        return {"skipped": True, "reason": "lock_engine_disabled"}
    vehicle_id = get_vehicle_id_by_imei(imei)
    if vehicle_id in LOCK_ENGINE_DISABLED_VEHICLE_IDS:
        logger.info(f"Lock engine command skipped for vehicle_id {vehicle_id} (IMEI {imei})")
        return {"skipped": True, "reason": "lock_engine_disabled"}
    commands = get_commands_by_imei(imei)
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
    import time
    sequence_start = time.time()
    logger.info(f"[GPS SEQUENCE] ========== START sequence_type={sequence_type}, imei={imei} ==========")
    
    commands = get_commands_by_imei(imei)
    if not commands:
        logger.info(f"[GPS SEQUENCE] ERROR: Команды для IMEI {imei} не найдены")
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
            step1_start = time.time()
            logger.info(f"[GPS SEQUENCE] Step 1/4: Opening locks...")
            try:
                open_cmd = commands.get("open", "")
                if open_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, open_cmd, token)
                    results["executed_commands"].append({"step": 1, "action": "open_locks", "result": result})
                    step1_duration = time.time() - step1_start
                    logger.info(f"[GPS SEQUENCE] Step 1/4 completed in {step1_duration:.3f}s")
                    logger.info(f"Замки автомобиля {imei} открыты")
                    
                    sleep_start = time.time()
                    logger.info(f"[GPS SEQUENCE] Sleeping 2s after step 1...")
                    await asyncio.sleep(2)  # Пауза между командами
                    sleep_duration = time.time() - sleep_start
                    logger.info(f"[GPS SEQUENCE] Sleep completed in {sleep_duration:.3f}s")
            except Exception as e:
                step1_duration = time.time() - step1_start
                logger.info(f"[GPS SEQUENCE] Step 1/4 FAILED after {step1_duration:.3f}s: {e}")
                error_msg = f"Ошибка открытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Выдать ключ
            step2_start = time.time()
            logger.info(f"[GPS SEQUENCE] Step 2/4: Giving key...")
            try:
                give_key_cmd = commands.get("give_key", "")
                if give_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, give_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "give_key", "result": result})
                    step2_duration = time.time() - step2_start
                    logger.info(f"[GPS SEQUENCE] Step 2/4 completed in {step2_duration:.3f}s")
                    logger.info(f"Ключ автомобиля {imei} выдан")
                    
                    sleep_start = time.time()
                    logger.info(f"[GPS SEQUENCE] Sleeping 2s after step 2...")
                    await asyncio.sleep(2)
                    sleep_duration = time.time() - sleep_start
                    logger.info(f"[GPS SEQUENCE] Sleep completed in {sleep_duration:.3f}s")
            except Exception as e:
                step2_duration = time.time() - step2_start
                logger.info(f"[GPS SEQUENCE] Step 2/4 FAILED after {step2_duration:.3f}s: {e}")
                error_msg = f"Ошибка выдачи ключа: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 3. Снова открыть замки
            step3_start = time.time()
            logger.info(f"[GPS SEQUENCE] Step 3/4: Opening locks again...")
            try:
                open_cmd = commands.get("open", "")
                if open_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, open_cmd, token)
                    results["executed_commands"].append({"step": 3, "action": "open_locks_again", "result": result})
                    step3_duration = time.time() - step3_start
                    logger.info(f"[GPS SEQUENCE] Step 3/4 completed in {step3_duration:.3f}s")
                    logger.info(f"Замки автомобиля {imei} открыты повторно")
                    
                    sleep_start = time.time()
                    logger.info(f"[GPS SEQUENCE] Sleeping 2s after step 3...")
                    await asyncio.sleep(2)
                    sleep_duration = time.time() - sleep_start
                    logger.info(f"[GPS SEQUENCE] Sleep completed in {sleep_duration:.3f}s")
            except Exception as e:
                step3_duration = time.time() - step3_start
                logger.info(f"[GPS SEQUENCE] Step 3/4 FAILED after {step3_duration:.3f}s: {e}")
                error_msg = f"Ошибка повторного открытия замков: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 4. Забрать ключ
            step4_start = time.time()
            logger.info(f"[GPS SEQUENCE] Step 4/4: Taking key...")
            try:
                take_key_cmd = commands.get("take_key", "")
                if take_key_cmd:
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, take_key_cmd, token)
                    results["executed_commands"].append({"step": 4, "action": "take_key", "result": result})
                    step4_duration = time.time() - step4_start
                    logger.info(f"[GPS SEQUENCE] Step 4/4 completed in {step4_duration:.3f}s")
                    logger.info(f"Ключ автомобиля {imei} забран")
            except Exception as e:
                step4_duration = time.time() - step4_start
                logger.info(f"[GPS SEQUENCE] Step 4/4 FAILED after {step4_duration:.3f}s: {e}")
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
            
            logger.info(f"[GPS SEQ] Starting complete_selfie_interior for {imei}")
            
            # 1. Заблокировать двигатель
            try:
                vehicle_id = get_vehicle_id_by_imei(imei)
                if imei in LOCK_ENGINE_DISABLED_IMEIS or vehicle_id in LOCK_ENGINE_DISABLED_VEHICLE_IDS:
                    logger.info(f"[GPS SEQ] Step 1: Lock engine SKIPPED (disabled for this vehicle)")
                    logger.info(f"Lock engine command skipped in execute_gps_sequence for IMEI {imei} (vehicle_id {vehicle_id})")
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": {"skipped": True, "reason": "lock_engine_disabled"}})
                else:
                    lock_engine_cmd = commands.get("lock_engine", "")
                    if lock_engine_cmd:
                        logger.info(f"[GPS SEQ] Step 1: Locking engine with command '{lock_engine_cmd}'")
                        result = await send_command_to_terminal(vehicle_id, lock_engine_cmd, token)
                        results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": result})
                        logger.info(f"Двигатель автомобиля {imei} заблокирован")
                        logger.info(f"[GPS SEQ] Step 1: Lock engine completed, waiting 2s")
                    else:
                        logger.info(f"[GPS SEQ] Step 1: Lock engine command not found")
                await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка блокировки двигателя: {e}"
                logger.info(f"[GPS SEQ] Step 1 ERROR: {error_msg}")
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 2. Забрать ключ
            try:
                take_key_cmd = commands.get("take_key", "")
                if take_key_cmd:
                    logger.info(f"[GPS SEQ] Step 2: Taking key with command '{take_key_cmd}'")
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, take_key_cmd, token)
                    results["executed_commands"].append({"step": 2, "action": "take_key", "result": result})
                    logger.info(f"Ключ автомобиля {imei} забран")
                    logger.info(f"[GPS SEQ] Step 2: Take key completed, waiting 2s")
                else:
                    logger.info(f"[GPS SEQ] Step 2: Take key command not found")
                await asyncio.sleep(2)
            except Exception as e:
                error_msg = f"Ошибка забора ключа: {e}"
                logger.info(f"[GPS SEQ] Step 2 ERROR: {error_msg}")
                results["errors"].append(error_msg)
                logger.error(error_msg)
            
            # 3. Закрыть замки
            try:
                close_cmd = commands.get("close", "")
                if close_cmd:
                    logger.info(f"[GPS SEQ] Step 3: Closing locks with command '{close_cmd}'")
                    vehicle_id = get_vehicle_id_by_imei(imei)
                    result = await send_command_to_terminal(vehicle_id, close_cmd, token)
                    results["executed_commands"].append({"step": 3, "action": "close_locks", "result": result})
                    logger.info(f"Замки автомобиля {imei} закрыты")
                    logger.info(f"[GPS SEQ] Step 3: Close locks completed")
                else:
                    logger.info(f"[GPS SEQ] Step 3: Close command not found")
            except Exception as e:
                error_msg = f"Ошибка закрытия замков: {e}"
                logger.info(f"[GPS SEQ] Step 3 ERROR: {error_msg}")
                results["errors"].append(error_msg)
                logger.error(error_msg)
                
        elif sequence_type == "complete_exterior":
            # Этап 5: Завершение - кузов
            # 1. Заблокировать двигатель
            # 2. Забрать ключ
            # 3. Закрыть замки
            
            # 1. Заблокировать двигатель
            try:
                vehicle_id = get_vehicle_id_by_imei(imei)
                if imei in LOCK_ENGINE_DISABLED_IMEIS or vehicle_id in LOCK_ENGINE_DISABLED_VEHICLE_IDS:
                    logger.info(f"Lock engine command skipped in execute_gps_sequence for IMEI {imei} (vehicle_id {vehicle_id})")
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": {"skipped": True, "reason": "lock_engine_disabled"}})
                else:
                    lock_engine_cmd = commands.get("lock_engine", "")
                    if lock_engine_cmd:
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
                vehicle_id = get_vehicle_id_by_imei(imei)
                if imei in LOCK_ENGINE_DISABLED_IMEIS or vehicle_id in LOCK_ENGINE_DISABLED_VEHICLE_IDS:
                    logger.info(f"Lock engine command skipped in execute_gps_sequence for IMEI {imei} (vehicle_id {vehicle_id})")
                    results["executed_commands"].append({"step": 1, "action": "lock_engine", "result": {"skipped": True, "reason": "lock_engine_disabled"}})
                else:
                    lock_engine_cmd = commands.get("lock_engine", "")
                    if lock_engine_cmd:
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
        logger.info(f"[GPS SEQUENCE] EXCEPTION: {error_msg}")
    
    sequence_duration = time.time() - sequence_start
    success_status = results.get("success", False)
    errors_count = len(results.get("errors", []))
    commands_count = len(results.get("executed_commands", []))
    logger.info(f"[GPS SEQUENCE] ========== END sequence_type={sequence_type}, imei={imei} ==========")
    logger.info(f"[GPS SEQUENCE] TOTAL duration: {sequence_duration:.3f}s, success={success_status}, commands={commands_count}, errors={errors_count}")
    
    return results
