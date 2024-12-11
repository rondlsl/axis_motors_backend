import requests


def get_auth_token(base_url: str, login: str, password: str) -> str:
    """
    Получает токен авторизации с API.

    :param base_url: Базовый URL API (например, https://hosting.glonasssoft.ru)
    :param login: Логин пользователя
    :param password: Пароль пользователя
    :return: Токен авторизации
    :raises Exception: Если запрос завершился ошибкой
    """
    url = f"{base_url}/api/v3/auth/login"
    payload = {"login": login, "password": password}

    response = requests.post(url, json=payload)

    if response.status_code == 200:
        auth_data = response.json()
        return auth_data.get("AuthId")  # Извлекаем только AuthId
    else:
        raise Exception(f"Ошибка авторизации: {response.status_code}, {response.text}")
