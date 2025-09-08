# Примеры запросов к API функционала "Гарант"

## Базовая аутентификация

### 1. Отправка SMS кода
```bash
curl -X POST "http://localhost:8000/auth/send_sms/" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "77001234567"}'
```

### 2. Верификация SMS кода (тестовый режим)
```bash
curl -X POST "http://localhost:8000/auth/verify_sms/" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "77001234567", "sms_code": "6666"}'
```

**Ответ:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

## Функционал гарантов

### 3. Получение информации о гаранте (для кнопки "?")
```bash
curl -X GET "http://localhost:8000/guarantor/info"
```

### 4. Создание заявки на гаранта
```bash
curl -X POST "http://localhost:8000/guarantor/request" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "guarantor_info": {
      "full_name": "Иванов Иван Иванович",
      "phone_number": "77009876543"
    },
    "reason": "Отказ в регистрации по причине недостаточного опыта вождения"
  }'
```

**Ответ если пользователь не найден:**
```json
{
  "message": "Пользователь не найден. SMS приглашение отправлено.",
  "user_exists": false,
  "sms_result": {
    "message": "TEST SMS sent successfully"
  }
}
```

**Ответ если пользователь найден:**
```json
{
  "message": "Заявка на гаранта создана успешно",
  "user_exists": true,
  "request_id": 1,
  "guarantor_name": "Иванов Иван Иванович"
}
```

### 5. Ответ на заявку гаранта (принять)
```bash
curl -X POST "http://localhost:8000/guarantor/respond/1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer GUARANTOR_ACCESS_TOKEN" \
  -d '{
    "accept": true
  }'
```

### 6. Ответ на заявку гаранта (отклонить)
```bash
curl -X POST "http://localhost:8000/guarantor/respond/1" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer GUARANTOR_ACCESS_TOKEN" \
  -d '{
    "accept": false,
    "rejection_reason": "Не могу взять на себя такую ответственность"
  }'
```

### 7. Получение информации о гарантах пользователя
```bash
curl -X GET "http://localhost:8000/guarantor/my-info" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Ответ:**
```json
{
  "sent_requests": [
    {
      "id": 1,
      "requestor_id": 1,
      "guarantor_id": 2,
      "status": "accepted",
      "reason": "Отказ в регистрации",
      "created_at": "2024-01-15T10:30:00",
      "responded_at": "2024-01-15T11:00:00",
      "requestor_name": "Петров Петр Петрович",
      "requestor_phone": "77001234567",
      "guarantor_name": "Иванов Иван Иванович",
      "guarantor_phone": "77009876543"
    }
  ],
  "received_requests": [],
  "my_clients": [],
  "my_guarantors": [
    {
      "id": 1,
      "guarantor_id": 2,
      "client_id": 1,
      "contract_signed": false,
      "sublease_contract_signed": false,
      "is_active": true,
      "created_at": "2024-01-15T11:00:00",
      "guarantor_name": "Иванов Иван Иванович",
      "guarantor_phone": "77009876543",
      "client_name": "Петров Петр Петрович",
      "client_phone": "77001234567"
    }
  ]
}
```

### 8. Подписание договора гаранта
```bash
curl -X POST "http://localhost:8000/guarantor/sign-contract" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "contract_type": "guarantor",
    "guarantor_relationship_id": 1
  }'
```

### 9. Подписание договора субаренды
```bash
curl -X POST "http://localhost:8000/guarantor/sign-contract" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "contract_type": "sublease",
    "guarantor_relationship_id": 1
  }'
```

### 10. Проверка платежеспособности пользователя
```bash
curl -X POST "http://localhost:8000/guarantor/check-user-eligibility" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "phone_number": "77009876543"
  }'
```

**Ответ:**
```json
{
  "user_exists": true,
  "user_id": 2,
  "is_eligible": true,
  "has_car_access": true,
  "user_name": "Иванов Иван Иванович",
  "reason": null
}
```

### 11. Получение списка договоров
```bash
curl -X GET "http://localhost:8000/guarantor/contracts" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Административные функции

### 12. Загрузка договора гаранта (только админы)
```bash
curl -X POST "http://localhost:8000/guarantor/upload-contract/guarantor" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -F "file=@contract_guarantor.pdf"
```

### 13. Загрузка договора субаренды (только админы)
```bash
curl -X POST "http://localhost:8000/guarantor/upload-contract/sublease" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -F "file=@contract_sublease.pdf"
```

### 14. Получение пользователей, ожидающих одобрения
```bash
curl -X GET "http://localhost:8000/admin/pending-users" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN"
```

### 15. Одобрение пользователя
```bash
curl -X POST "http://localhost:8000/admin/approve-user" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -d '{
    "user_id": 3,
    "approved": true
  }'
```

### 16. Отклонение пользователя с предложением гаранта
```bash
curl -X POST "http://localhost:8000/admin/approve-user" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ADMIN_ACCESS_TOKEN" \
  -d '{
    "user_id": 3,
    "approved": false,
    "rejection_reason": "Недостаточный стаж вождения, рекомендуется воспользоваться услугой гаранта"
  }'
```

## Python примеры с использованием requests

### Создание заявки на гаранта
```python
import requests

# Получение токена
auth_response = requests.post(
    "http://localhost:8000/auth/verify_sms/",
    json={"phone_number": "77001234567", "sms_code": "6666"}
)
token = auth_response.json()["access_token"]

# Создание заявки на гаранта
headers = {"Authorization": f"Bearer {token}"}
data = {
    "guarantor_info": {
        "full_name": "Иванов Иван Иванович",
        "phone_number": "77009876543"
    },
    "reason": "Отказ в регистрации"
}

response = requests.post(
    "http://localhost:8000/guarantor/request",
    json=data,
    headers=headers
)

print(response.json())
```

### Проверка статуса заявок
```python
import requests

headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:8000/guarantor/my-info",
    headers=headers
)

guarantor_info = response.json()
print("Отправленные заявки:", len(guarantor_info["sent_requests"]))
print("Полученные заявки:", len(guarantor_info["received_requests"]))
print("Мои клиенты:", len(guarantor_info["my_clients"]))
print("Мои гаранты:", len(guarantor_info["my_guarantors"]))
```

## JavaScript примеры с использованием fetch

### Создание заявки на гаранта
```javascript
// Получение токена
const authResponse = await fetch('http://localhost:8000/auth/verify_sms/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    phone_number: '77001234567',
    sms_code: '6666'
  })
});

const authData = await authResponse.json();
const token = authData.access_token;

// Создание заявки на гаранта
const guarantorResponse = await fetch('http://localhost:8000/guarantor/request', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    guarantor_info: {
      full_name: 'Иванов Иван Иванович',
      phone_number: '77009876543'
    },
    reason: 'Отказ в регистрации'
  })
});

const result = await guarantorResponse.json();
console.log(result);
```

## Коды ошибок

### 400 Bad Request
- Неверные данные в запросе
- Попытка назначить себя гарантом
- Активная заявка уже существует

### 401 Unauthorized
- Неверный или истекший токен
- Отсутствует заголовок Authorization

### 403 Forbidden
- Недостаточно прав (для админских функций)

### 404 Not Found
- Пользователь не найден
- Заявка не найдена
- Отношение гарант-клиент не найдено

### 422 Unprocessable Entity
- Ошибки валидации данных
- Неверный формат номера телефона
- Неверный формат имени

## Тестовые данные

Для тестирования используйте следующие тестовые номера:
- `77001234567` - основной тестовый пользователь
- `77009876543` - тестовый гарант
- `77007007070` - тестовый механик (уже существует в системе)

Тестовый SMS код: `6666`
