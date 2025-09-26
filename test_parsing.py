# Тест парсинга auto_class
auto_class = "{A, B, C}"

print(f"Исходная строка: {auto_class}")

raw = auto_class.strip()
if raw.startswith("{") and raw.endswith("}"):
    raw = raw[1:-1]

print(f"После удаления скобок: {raw}")

# Убираем все кавычки и пробелы, затем разбиваем по запятым
raw = raw.replace('"', '').replace("'", "").replace(' ', '')
print(f"После удаления кавычек и пробелов: {raw}")

allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
print(f"Результат: {allowed_classes}")

# Проверяем валидность
valid_classes = ['A', 'B', 'C']
valid_count = sum(1 for cls in allowed_classes if cls in valid_classes)
print(f"Валидных классов: {valid_count}/{len(allowed_classes)}")
