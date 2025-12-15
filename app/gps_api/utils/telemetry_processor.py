import re
from typing import Dict, List, Any, Optional
from datetime import datetime

from app.gps_api.schemas_telemetry import VehicleTelemetryResponse


def parse_numeric(value: str) -> float:
    """Парсит числовое значение из строки"""
    if not value or value.lower() in ["данных нет", "нет данных", ""]:
        return 0.0
    # Заменяем запятую на точку и ищем число
    m = re.search(r'[-+]?\d*\.?\d+', value.replace(",", "."))
    return float(m.group()) if m else 0.0


def parse_int(value: str) -> int:
    """Парсит целое число из строки"""
    return int(parse_numeric(value))


def parse_datetime(dt_str: str) -> datetime:
    """Парсит дату и время из строки"""
    if dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


def extract_sensor_value(items: List[Dict], key_name: str) -> str:
    """Извлекает значение сенсора по name или parameterName (case-insensitive)"""
    for item in items:
        name = item.get("name", "").lower()
        param_name = item.get("parameterName", "").lower()
        key_lower = key_name.lower()
        if name == key_lower or param_name == key_lower:
            return item.get("value", "").strip()
    return ""


def extract_first_match(items: List[Dict], possible_keys: List[str]) -> str:
    """Возвращает значение для первого найденного ключа (регистрозависимый поиск)"""
    lower_to_value = {item.get("name", "").lower(): item.get("value", "").strip() for item in items}
    for key in possible_keys:
        val = lower_to_value.get(key.lower())
        if val is not None and val != "":
            return val
    return ""


def extract_param64_value(regs: List[Dict[str, Any]], pkg: List[Dict[str, Any]]) -> Optional[int]:
    """Возвращает числовое значение param64 (0-255), если оно присутствует."""
    # Ищем в RegistredSensors по name
    raw_value = extract_first_match(regs, ["Статус (param64)", "param64"])
    if not raw_value:
        # Ищем в PackageItems по name
        raw_value = extract_first_match(pkg, ["param64"])
    if not raw_value:
        # Ищем в PackageItems по parameterName
        for item in pkg:
            if item.get("parameterName", "").lower() == "param64":
                raw_value = item.get("value", "").strip()
                break
    if not raw_value:
        return None
    try:
        # Парсим числовое значение (может быть просто "0" или "1" или "255")
        num_value = int(parse_numeric(raw_value))
        # Проверяем диапазон 0-255
        if 0 <= num_value <= 255:
            return num_value
        return None
    except Exception:
        return None


def decode_param64_flags(byte_value: Optional[int]) -> Optional[Dict[str, bool]]:
    """Преобразует значение param64 в набор булевых флагов."""
    if byte_value is None:
        return None
    return {
        "ignition": bool((byte_value >> 7) & 1),
        "doors": bool((byte_value >> 6) & 1),
        "glass": bool((byte_value >> 5) & 1),
        "hood": bool((byte_value >> 4) & 1),
        "lights": bool((byte_value >> 3) & 1),
        "brake": bool((byte_value >> 2) & 1),
        "trunk": bool((byte_value >> 1) & 1),
        "engine_lock": bool(byte_value & 1),
    }


def process_glonassoft_data(glonassoft_data: Dict[str, Any], car_name: str = "") -> VehicleTelemetryResponse:
    """Обрабатывает данные от Глонассофт и преобразует в структурированный формат"""
    
    print(f"[TELEMETRY PROCESSOR] Processing data for car: {car_name}")
    print(f"[TELEMETRY PROCESSOR] Raw data keys: {list(glonassoft_data.keys()) if isinstance(glonassoft_data, dict) else 'Not a dict'}")
    
    # Извлекаем основные данные
    pkg = glonassoft_data.get("PackageItems", [])
    regs = glonassoft_data.get("RegistredSensors", [])
    unregs = glonassoft_data.get("UnregisteredSensors", [])
    general = glonassoft_data.get("GeneralSensors", [])
    param64_flags = decode_param64_flags(extract_param64_value(regs, pkg))
    
    print(f"[TELEMETRY PROCESSOR] PackageItems count: {len(pkg)}")
    print(f"[TELEMETRY PROCESSOR] RegistredSensors count: {len(regs)}")
    print(f"[TELEMETRY PROCESSOR] UnregisteredSensors count: {len(unregs)}")
    print(f"[TELEMETRY PROCESSOR] GeneralSensors count: {len(general)}")
    
    # Основная информация
    imei = glonassoft_data.get("imei", "")
    vehicle_id = glonassoft_data.get("vehicleid", 0)
    device_type_id = glonassoft_data.get("devicetypeid", 0)
    last_active_time = parse_datetime(glonassoft_data.get("lastactivetime", ""))
    is_online = glonassoft_data.get("isonline", False)
    is_moving = glonassoft_data.get("ismoving", False)
    
    is_special_car = (vehicle_id == 800298270 or imei == "860803068155890")
    
    # Координаты
    latitude = glonassoft_data.get("latitude", 0.0)
    longitude = glonassoft_data.get("longitude", 0.0)
    
    # Основные параметры движения
    # Скорость (PackageItems) - как в azv_motors_cars_v2
    raw_speed = extract_sensor_value(pkg, "Скорость")
    try:
        speed = parse_numeric(raw_speed) if raw_speed else 0.0
    except Exception:
        speed = 0.0
    
    course = parse_numeric(extract_sensor_value(pkg, "Курс"))
    altitude = parse_numeric(extract_sensor_value(pkg, "Высота над уровнем моря"))
    
    # Спутники
    gps_satellites = parse_int(extract_sensor_value(general, "Спутники GPS"))
    glonass_satellites = parse_int(extract_sensor_value(general, "Спутники ГЛОНАСС"))
    galileo_satellites = parse_int(extract_sensor_value(general, "Спутники Galileo"))
    beidou_satellites = parse_int(extract_sensor_value(general, "Спутники Beidou"))
    total_satellites = gps_satellites + glonass_satellites + galileo_satellites + beidou_satellites
    
    # Напряжение
    board_voltage = parse_numeric(extract_sensor_value(general, "Бортовое напряжение"))
    
    # Двигатель
    engine_rpm = None
    rpm_keys = ["Обороты двигателя (param69)", "Обороты двигателя (param73)", "Обороты двигателя (can101)", "Обороты двигателя (engine_rpm)"]
    for key in rpm_keys:
        rpm_value = extract_sensor_value(regs, key)
        if rpm_value and rpm_value.lower() not in ["данных нет", "нет данных"]:
            engine_rpm = parse_int(rpm_value.replace(" об/мин", "").strip())
            break
    
    engine_temperature = None
    temp_keys = ["Температура двигателя (can102)", "Температура двигателя (engine_coolant_temp)"]
    for key in temp_keys:
        temp_value = extract_sensor_value(regs, key)
        if temp_value and temp_value.lower() not in ["данных нет", "нет данных"]:
            engine_temperature = parse_numeric(temp_value.replace(" C°", ""))
            break
    
    engine_hours = None
    hours_keys = ["Часы работы двигателя", "engine_hours", "can_engine_hours"]
    for key in hours_keys:
        hours_value = extract_first_match(unregs, [key])
        if hours_value and hours_value.lower() not in ["данных нет", "нет данных"]:
            engine_hours = parse_numeric(hours_value)
            break
    
    is_engine_on = engine_rpm is not None and engine_rpm > 0
    
    # Топливо и пробег
    fuel_level = None
    
    if is_special_car:
        fuel_value = extract_sensor_value(regs, "Уровень топлива (param70)")
        if fuel_value and fuel_value.lower() not in ["данных нет", "нет данных"]:
            fuel_str = fuel_value.replace(" л", "").replace("л", "").strip()
            parsed_fuel = parse_numeric(fuel_str)
            if parsed_fuel > 0:
                fuel_level = parsed_fuel
        
        if fuel_level is None:
            raw_param70 = extract_first_match(pkg, ["param70"])
            if raw_param70 and raw_param70.lower() not in ["данных нет", "нет данных"]:
                try:
                    parsed_value = parse_numeric(raw_param70)
                    if 0 < parsed_value <= 150:
                        fuel_level = parsed_value
                except Exception:
                    pass
    else:
        fuel_keys = [
            "Уровень топлива (param70)",
            "Уровень топлива (can100)",
            "Уровень топлива (can_fuel_volume)",
            "Заряд батареи (param67)",
        ]
        for key in fuel_keys:
            fuel_value = extract_sensor_value(regs, key)
            if fuel_value and fuel_value.lower() not in ["данных нет", "нет данных"]:
                fuel_str = fuel_value.replace(" л", "").replace("л", "").strip()
                fuel_level = parse_numeric(fuel_str)
                break

        # Fallback: если в RegistredSensors нет уровня топлива, пробуем взять param70 из PackageItems
        if fuel_level is None:
            raw_param70 = extract_first_match(pkg, ["param70"])
            if raw_param70 and raw_param70.lower() not in ["данных нет", "нет данных"]:
                try:
                    parsed_value = parse_numeric(raw_param70)
                    if 0 < parsed_value <= 150:
                        fuel_level = parsed_value
                except Exception:
                    pass
    
    if fuel_level is not None and fuel_level <= 0:
        fuel_level = None
    
    fuel_consumption = None
    consumption_keys = ["can_fuel_consumpt", "Расход топлива"]
    for key in consumption_keys:
        consumption_value = extract_first_match(unregs, [key])
        if consumption_value and consumption_value.lower() not in ["данных нет", "нет данных"]:
            fuel_consumption = parse_numeric(consumption_value)
            break
    
    mileage = None
    mileage_keys = ["Пробег (param68)", "Пробег (can97)", "Датчик пробега (can_mileage)", "Пробег (can33)"]
    for key in mileage_keys:
        mileage_value = extract_sensor_value(regs, key)
        if mileage_value and mileage_value.lower() not in ["данных нет", "нет данных"]:
            mileage = parse_numeric(mileage_value)
            break
    
    # Двери
    front_right_door_open = False
    front_left_door_open = False
    rear_right_door_open = False
    rear_left_door_open = False
    
    # Ищем данные о дверях в RegistredSensors
    fr_door = extract_first_match(regs, ["ПП Дверь (can42)", "ПП Дверь", "passenger front door"])
    fl_door = extract_first_match(regs, ["ПЛ Дверь (can44)", "ПЛ Дверь", "driver front door"])
    rr_door = extract_first_match(regs, ["ЗП Дверь (can48)", "ЗП Дверь", "rear right door"])
    rl_door = extract_first_match(regs, ["ЗЛ Дверь (can46)", "ЗЛ Дверь", "rear left door"])
    
    if fr_door or fl_door or rr_door or rl_door:
        # Формат RegistredSensors: "Открыта"/"Закрыта"
        front_right_door_open = bool(fr_door and fr_door.lower() == "открыта")
        front_left_door_open = bool(fl_door and fl_door.lower() == "открыта")
        rear_right_door_open = bool(rr_door and rr_door.lower() == "открыта")
        rear_left_door_open = bool(rl_door and rl_door.lower() == "открыта")
    else:
        # Проверяем param66 в PackageItems
        # param66 = 0 означает все двери закрыты, 1 = хотя бы одна открыта
        param66_value = extract_first_match(pkg, ["param66"])
        if param66_value:
            try:
                param66_int = int(parse_numeric(param66_value))
                # Если param66 = 1, значит хотя бы одна дверь открыта
                # Но мы не знаем какая именно, поэтому считаем что все закрыты если 0
                if param66_int == 1:
                    # Хотя бы одна дверь открыта, но не знаем какая - оставляем все False
                    # или можно установить все в True, но лучше оставить False для безопасности
                    pass
            except Exception:
                pass
        
        # Формат UnregisteredSensors: CanSafetyFlags_* = "True"/"False"
        # False = дверь открыта, True = дверь закрыта
        fr_door_unreg = extract_first_match(unregs, ["CanSafetyFlags_passangerdoor"])
        fl_door_unreg = extract_first_match(unregs, ["CanSafetyFlags_driverdoor"])
        rr_door_unreg = extract_first_match(unregs, ["CanSafetyFlags_frontdoor"])
        rl_door_unreg = extract_first_match(unregs, ["CanSafetyFlags_backdoor"])
        
        front_right_door_open = fr_door_unreg.lower() == "false" if fr_door_unreg else False
        front_left_door_open = fl_door_unreg.lower() == "false" if fl_door_unreg else False
        rear_right_door_open = rr_door_unreg.lower() == "false" if rr_door_unreg else False
        rear_left_door_open = rl_door_unreg.lower() == "false" if rl_door_unreg else False
    
    # Замки дверей
    front_right_door_locked = True
    front_left_door_locked = True
    rear_right_door_locked = True
    rear_left_door_locked = True
    central_locks_locked = True
    
    # Ищем данные о замках в RegistredSensors
    fr_lock = extract_first_match(regs, ["ПП Замок (can43)", "ПП Замок", "front right lock"])
    fl_lock = extract_first_match(regs, ["ПЛ Замок (can45)", "ПЛ Замок", "front left lock"])
    rr_lock = extract_first_match(regs, ["ЗП Замок (can49)", "ЗП Замок", "rear right lock"])
    rl_lock = extract_first_match(regs, ["ЗЛ Замок (can47)", "ЗЛ Замок", "rear left lock"])
    
    if fr_lock or fl_lock or rr_lock or rl_lock:
        # Формат RegistredSensors: "Открыт"/"Закрыт"
        front_right_door_locked = bool(fr_lock and fr_lock.lower() != "открыт")
        front_left_door_locked = bool(fl_lock and fl_lock.lower() != "открыт")
        rear_right_door_locked = bool(rr_lock and rr_lock.lower() != "открыт")
        rear_left_door_locked = bool(rl_lock and rl_lock.lower() != "открыт")
    else:
        # Формат UnregisteredSensors: CanSafetyFlags_* = "True"/"False"
        # True = замок заблокирован, False = замок открыт
        fr_lock_unreg = extract_first_match(unregs, ["CanSafetyFlags_passangerdoor"])
        fl_lock_unreg = extract_first_match(unregs, ["CanSafetyFlags_driverdoor"])
        rr_lock_unreg = extract_first_match(unregs, ["CanSafetyFlags_frontdoor"])
        rl_lock_unreg = extract_first_match(unregs, ["CanSafetyFlags_backdoor"])
        
        front_right_door_locked = fr_lock_unreg.lower() == "true" if fr_lock_unreg else True
        front_left_door_locked = fl_lock_unreg.lower() == "true" if fl_lock_unreg else True
        rear_right_door_locked = rr_lock_unreg.lower() == "true" if rr_lock_unreg else True
        rear_left_door_locked = rl_lock_unreg.lower() == "true" if rl_lock_unreg else True
    
    # Центральные замки
    central_locks = extract_first_match(regs, ["Замки (can40)", "Замки (центральный)", "Замки"])
    if central_locks:
        central_locks_locked = bool(central_locks.lower().startswith("закрыт"))
    else:
        central_locks_unreg = extract_first_match(unregs, ["CanSafetyFlags_lock"])
        if central_locks_unreg:
            central_locks_locked = central_locks_unreg.lower() == "true"
        else:
            central_locks_locked = True
    
    # Стекла
    fl_win = extract_first_match(regs, ["ПЛ Стекло (can50)", "ПЛ Стекло", "front left window"])
    fr_win = extract_first_match(regs, ["ПП Стекло (can51)", "ПП Стекло", "front right window"])
    rl_win = extract_first_match(regs, ["ЗЛ Стекло (can52)", "ЗЛ Стекло", "rear left window"])
    rr_win = extract_first_match(regs, ["ЗП Стекло (can53)", "ЗП Стекло", "rear right window"])
    
    front_left_window_closed = True if not fl_win else (fl_win.lower() == "закрыто")
    front_right_window_closed = True if not fr_win else (fr_win.lower() == "закрыто")
    rear_left_window_closed = True if not rl_win else (rl_win.lower() == "закрыто")
    rear_right_window_closed = True if not rr_win else (rr_win.lower() == "закрыто")
    
    # Капот и багажник
    hood_keys = ["Капот (can37)", "Капот (in0;iobits0)", "Капот (can34)"]
    hood_value = extract_first_match(regs, hood_keys)
    hood_open = bool(hood_value and hood_value.lower() == "открыт")
    
    trunk_keys = ["Багажник (can35)", "Багажник (can38)"]
    trunk_value = extract_first_match(regs, trunk_keys)
    trunk_unreg = None
    if trunk_value:
        trunk_open = bool(trunk_value.lower() == "открыт")
    else:
        trunk_unreg = extract_first_match(unregs, ["CanSafetyFlags_trunk"])
        trunk_open = trunk_unreg.lower() == "false" if trunk_unreg else True
    
    # Свет и тормоза
    lights_keys = ["Фары (can38)", "Ближний свет (can41)"]
    lights_value = extract_first_match(regs, lights_keys)
    lights_on = bool(lights_value and (lights_value.lower().startswith("вкл") or lights_value.lower() == "включен"))
    
    auto_light_keys = ["Режим света AUTO (can42)", "Режим AUTO света"]
    auto_light_value = extract_first_match(regs, auto_light_keys)
    light_auto_mode = bool(auto_light_value and auto_light_value.lower().startswith("вкл"))
    
    handbrake_keys = ["Стояночный тормоз (can41)", "Парковочный тормоз (can43)"]
    handbrake_value = extract_first_match(regs, handbrake_keys)
    if handbrake_value:
        handbrake_on = bool(handbrake_value.lower().startswith("вкл"))
    else:
        handbrake_unreg = extract_first_match(unregs, ["CanSafetyFlags_handbrake"])
        handbrake_on = handbrake_unreg.lower() == "false" if handbrake_unreg else True
    
    # Если двигатель выключен, ручник считается включенным
    if not is_engine_on:
        handbrake_on = True
    
    brake_pedal_pressed = False
    brake_keys = ["Педаль тормоза (can39)", "Педаль тормоза"]
    brake_value = extract_first_match(regs, brake_keys)
    if brake_value:
        brake_pedal_pressed = brake_value.lower() == "нажата"
    
    # Дополнительные параметры
    steering_angle = None
    steering_keys = ["Угол поворота руля (can44)", "Угол поворота руля"]
    steering_value = extract_first_match(regs, steering_keys)
    if steering_value:
        steering_angle = parse_numeric(steering_value)
    
    gas_pedal_position = None
    gas_keys = ["Педаль газа (can39)", "Педаль газа (can40)"]
    gas_value = extract_first_match(regs, gas_keys)
    if gas_value:
        gas_pedal_position = parse_numeric(gas_value)
    
    brake_force = None
    brake_force_keys = ["Тормозное усилие (can36)", "Тормозное усилие"]
    brake_force_value = extract_first_match(regs, brake_force_keys)
    if brake_force_value:
        brake_force = parse_numeric(brake_force_value)
    
    # Безопасность
    driver_seatbelt_fastened = True
    seatbelt_keys = ["Ремень водителя (can37)", "Ремень водителя"]
    seatbelt_value = extract_first_match(regs, seatbelt_keys)
    if seatbelt_value:
        driver_seatbelt_fastened = seatbelt_value.lower() != "нет"
    
    alarm_active = False
    alarm_unreg = extract_first_match(unregs, ["CanSafetyFlags_alarm"])
    if alarm_unreg:
        alarm_active = alarm_unreg.lower() == "true"
    
    ignition_on = False
    engine_lock_active = False

    # Ищем зажигание в RegistredSensors
    ignition_reg = extract_first_match(regs, ["Зажигание (param65)", "Зажигание (can45)", "Зажигание"])  
    if ignition_reg:
        ignition_on = ignition_reg.lower().startswith("вкл")
    else:
        # Ищем в PackageItems (param65 для некоторых устройств, например Tucson)
        param65_value = extract_first_match(pkg, ["param65"])
        if param65_value:
            try:
                ignition_on = int(parse_numeric(param65_value)) == 1
            except Exception:
                ignition_on = False
        else:
            # Ищем в UnregisteredSensors
            ignition_unreg = extract_first_match(unregs, ["CanSafetyFlags_ignition"])
            if ignition_unreg:
                ignition_on = ignition_unreg.lower() == "true"

    # Применяем param64, если он присутствует (param64 имеет приоритет над другими источниками)
    if param64_flags:
        # Зажигание: bit1 (128) = 1 → зажигание включено
        ignition_on = param64_flags["ignition"]
        if ignition_on and not is_engine_on:
            is_engine_on = True

        # Двери и замки: bit2 (64) = 1 → двери открыты, замки открыты
        doors_open = param64_flags["doors"]
        front_right_door_open = doors_open
        front_left_door_open = doors_open
        rear_right_door_open = doors_open
        rear_left_door_open = doors_open

        doors_locked = not doors_open
        front_right_door_locked = doors_locked
        front_left_door_locked = doors_locked
        rear_right_door_locked = doors_locked
        rear_left_door_locked = doors_locked
        central_locks_locked = doors_locked

        # Стекла: bit3 (32) = 1 → стекла открыты
        windows_open = param64_flags["glass"]
        front_left_window_closed = not windows_open
        front_right_window_closed = not windows_open
        rear_left_window_closed = not windows_open
        rear_right_window_closed = not windows_open

        # Капот: bit4 (16) = 1 → капот открыт
        hood_open = param64_flags["hood"]
        
        # Свет: bit5 (8) = 1 → свет включен
        lights_on = param64_flags["lights"]
        
        # Педаль тормоза: bit6 (4) = 1 → педаль нажата
        brake_pedal_pressed = param64_flags["brake"]
        
        # Багажник: bit7 (2) = 1 → багажник открыт
        trunk_open = param64_flags["trunk"]
        
        # Блокировка двигателя: bit8 (1) = 1 → блокировка активна
        engine_lock_active = param64_flags["engine_lock"]
    
    # Связь
    gsm_signal = None
    gsm_value = extract_first_match(unregs, ["gsm"])
    if gsm_value:
        gsm_signal = parse_int(gsm_value)
    
    connection_status_net = None
    net_value = extract_first_match(unregs, ["ConnectStatus_net"])
    if net_value:
        connection_status_net = parse_int(net_value)
    
    connection_status_server1 = False
    server1_value = extract_first_match(unregs, ["ConnectStatus_server1"])
    if server1_value:
        connection_status_server1 = server1_value.lower() == "true"
    
    connection_status_server2 = False
    server2_value = extract_first_match(unregs, ["ConnectStatus_server2"])
    if server2_value:
        connection_status_server2 = server2_value.lower() == "true"
    
    connection_status_server3 = False
    server3_value = extract_first_match(unregs, ["ConnectStatus_server3"])
    if server3_value:
        connection_status_server3 = server3_value.lower() == "true"
    
    # Акселерометр
    acceleration_x = None
    acc_x_value = extract_first_match(unregs, ["acc_x"])
    if acc_x_value:
        acceleration_x = parse_numeric(acc_x_value)
    
    acceleration_y = None
    acc_y_value = extract_first_match(unregs, ["acc_y"])
    if acc_y_value:
        acceleration_y = parse_numeric(acc_y_value)
    
    acceleration_z = None
    acc_z_value = extract_first_match(unregs, ["acc_z"])
    if acc_z_value:
        acceleration_z = parse_numeric(acc_z_value)
    
    # Точность GPS
    hdop = None
    hdop_value = extract_first_match(unregs, ["Hdop"])
    if hdop_value:
        hdop = parse_numeric(hdop_value)
    
    pdop = None
    pdop_value = extract_first_match(unregs, ["pdop"])
    if pdop_value:
        pdop = parse_int(pdop_value)
    
    print(f"[TELEMETRY PROCESSOR] Final processed data - IMEI: {imei}, Speed: {speed}, Engine: {is_engine_on}")
    
    return VehicleTelemetryResponse(
        # Основная информация
        imei=imei,
        vehicle_id=vehicle_id,
        car_name=car_name,
        device_type_id=device_type_id,
        last_active_time=last_active_time,
        is_online=is_online,
        is_moving=is_moving,
        
        # Координаты
        latitude=latitude,
        longitude=longitude,
        
        # Основные параметры движения
        speed=speed,
        course=course,
        altitude=altitude,
        
        # Спутники
        gps_satellites=gps_satellites,
        glonass_satellites=glonass_satellites,
        galileo_satellites=galileo_satellites,
        beidou_satellites=beidou_satellites,
        total_satellites=total_satellites,
        
        # Напряжение
        board_voltage=board_voltage,
        
        # Двигатель
        engine_rpm=engine_rpm,
        engine_temperature=engine_temperature,
        engine_hours=engine_hours,
        is_engine_on=is_engine_on,
        
        # Топливо и пробег
        fuel_level=fuel_level,
        fuel_consumption=fuel_consumption,
        mileage=mileage,
        
        # Двери
        front_right_door_open=front_right_door_open,
        front_left_door_open=front_left_door_open,
        rear_right_door_open=rear_right_door_open,
        rear_left_door_open=rear_left_door_open,
        
        # Замки дверей
        front_right_door_locked=front_right_door_locked,
        front_left_door_locked=front_left_door_locked,
        rear_right_door_locked=rear_right_door_locked,
        rear_left_door_locked=rear_left_door_locked,
        central_locks_locked=central_locks_locked,
        
        # Стекла
        front_right_window_closed=front_right_window_closed,
        front_left_window_closed=front_left_window_closed,
        rear_right_window_closed=rear_right_window_closed,
        rear_left_window_closed=rear_left_window_closed,
        
        # Капот и багажник
        hood_open=hood_open,
        trunk_open=trunk_open,
        
        # Свет и тормоза
        lights_on=lights_on,
        light_auto_mode=light_auto_mode,
        handbrake_on=handbrake_on,
        brake_pedal_pressed=brake_pedal_pressed,
        engine_lock_active=engine_lock_active,
        
        # Дополнительные параметры
        steering_angle=steering_angle,
        gas_pedal_position=gas_pedal_position,
        brake_force=brake_force,
        
        # Безопасность
        driver_seatbelt_fastened=driver_seatbelt_fastened,
        alarm_active=alarm_active,
        ignition_on=ignition_on,
        
        # Связь
        gsm_signal=gsm_signal,
        connection_status_net=connection_status_net,
        connection_status_server1=connection_status_server1,
        connection_status_server2=connection_status_server2,
        connection_status_server3=connection_status_server3,
        
        # Акселерометр
        acceleration_x=acceleration_x,
        acceleration_y=acceleration_y,
        acceleration_z=acceleration_z,
        
        # Точность GPS
        hdop=hdop,
        pdop=pdop,
    )
