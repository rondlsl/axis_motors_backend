import requests
from typing import List, Union, Dict

from fastapi import HTTPException


def get_last_vehicles_data(token: str, ids: List[int]) -> Union[dict, None]:
    """
    Функция для получения последних данных объектов. (локация, номер, скорость)

    :param token: Токен авторизации (строка).
    :param ids: Список ID объектов (список чисел) - ID Машин.
    :return: Ответ от сервера в виде словаря или None в случае ошибки.
    """
    url = "https://regions.glonasssoft.ru/api/v3/vehicles/getlastdata"

    headers = {
        "X-Auth": token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, json=ids, headers=headers)
        response.raise_for_status()  # Проверка на ошибки
        return response.json()  # Парсинг ответа в JSON

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None


def get_vehicle_data(token: str, vehicle_id: int) -> Union[dict, None]:
    """
    Функция для получения данных объекта по ID.

    :param token: Токен авторизации (строка).
    :param vehicle_id: ID объекта (число) - ID машины.
    :return: Ответ от сервера в виде словаря или None в случае ошибки.
    """
    url = f"https://regions.glonasssoft.ru/api/v2.0/monitoringVehicles/devicestatebyimei?imei={vehicle_id}&timezone=5"

    headers = {
        "X-Auth": token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Проверка на ошибки
        return response.json()  # Парсинг ответа в JSON

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None


#   Пример использования
#   token = "ae9e1482-c739-49c0-8146-8cedc56548c8"  # Замените на ваш токен
#   ids = [1]  # Замените на массив ваших ID
#   result = get_last_vehicle_data(token, ids)
#   print("Результат:", result)


def send_command_to_terminal(
        vehicle_id: int,
        command: str,
        token: str,
        retries: int = 3,
        id_template: Union[int, None] = None
) -> Dict:
    """
    Функция для отправки команды на терминал с встроенной обработкой ошибок.

    :param vehicle_id: Идентификатор объекта/ТС (число).
    :param command: Текст отправляемой команды (строка).
    :param token: Токен авторизации (строка). По умолчанию использует глобальный AUTH_TOKEN.
    :param retries: Количество попыток отправки на терминал (число). По умолчанию 1.
    :param id_template: ID шаблона команды (число или None). По умолчанию None.
    :return: Ответ от сервера в виде словаря.
    :raises HTTPException: В случае ошибки отправки команды.
    """
    # URL для запроса
    url = "https://regions.glonasssoft.ru/api/v3/Vehicles/cmd/create"

    # Заголовки с токеном авторизации
    headers = {
        "X-Auth": token,
        "Content-Type": "application/json",
    }

    # Тело запроса
    payload = {
        "id": vehicle_id,
        "command": command,
        "retries": retries,
        "idTemplate": id_template,
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Проверка на ошибки

        # Удаляем лишние кавычки с помощью strip()
        command_id = response.text.strip('"')
        return {"command_id": command_id}

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при выполнении запроса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка отправки команды: {command}")
