#!/usr/bin/env python3
"""
Прямой тест отправки push-уведомления через Expo API
Используйте этот скрипт для проверки что Expo API доступен с сервера
"""

import asyncio
import httpx
import sys

async def test_push_direct(token: str):
    """Тест прямой отправки в Expo Push API"""
    
    print(f"🧪 Тестирование прямой отправки push-уведомления")
    print(f"📱 Token: {token[:50]}...")
    print()
    
    message = {
        "to": token,
        "title": "🧪 Прямой тест",
        "body": "Это прямой тест из Python скрипта",
        "sound": "default",
        "priority": "high",
        "channelId": "default"
    }
    
    urls = [
        "https://exp.host/--/api/v2/push/send",
        "https://api.expo.dev/v2/push/send"
    ]
    
    for url in urls:
        print(f"🔄 Попытка отправки на: {url}")
        
        try:
            timeout = httpx.Timeout(30.0, connect=30.0)
            
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.post(url, json=message)
                
                print(f"📊 Статус: {response.status_code}")
                print(f"📄 Ответ: {response.text}")
                print()
                
                if response.status_code == 200:
                    result = response.json()
                    data = result.get('data', {})
                    
                    if isinstance(data, list):
                        data = data[0] if data else {}
                    
                    if data.get('status') == 'ok':
                        print(f"✅ УСПЕХ! Push отправлен через {url}")
                        print(f"🆔 Ticket ID: {data.get('id')}")
                        return True
                    else:
                        print(f"❌ Ошибка Expo: {data.get('message', 'Unknown')}")
                        print(f"   Детали: {data.get('details', {})}")
                else:
                    print(f"❌ HTTP ошибка: {response.status_code}")
                    
        except httpx.TimeoutException as e:
            print(f"⏱️ Timeout: {e}")
        except httpx.NetworkError as e:
            print(f"🌐 Network error: {e}")
        except Exception as e:
            print(f"❌ Ошибка: {type(e).__name__}: {e}")
        
        print()
    
    print("❌ Все попытки не удались")
    return False


async def test_network():
    """Проверка сетевой доступности"""
    print("🌐 Проверка сетевого подключения...")
    print()
    
    test_urls = [
        "https://google.com",
        "https://exp.host",
        "https://api.expo.dev"
    ]
    
    for url in test_urls:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                print(f"✅ {url} - доступен (статус {response.status_code})")
        except Exception as e:
            print(f"❌ {url} - недоступен: {e}")
    
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Ошибка: Не указан Expo Push Token")
        print()
        print("Использование:")
        print(f"  python3 {sys.argv[0]} <expo-push-token>")
        print()
        print("Пример:")
        print(f"  python3 {sys.argv[0]} 'ExponentPushToken[xxxxxx]'")
        print()
        print("💡 Токен можно взять из response /notifications/test_push_by_phone")
        sys.exit(1)
    
    token = sys.argv[1]
    
    # Сначала проверяем сеть
    asyncio.run(test_network())
    
    # Затем пытаемся отправить push
    success = asyncio.run(test_push_direct(token))
    
    sys.exit(0 if success else 1)

