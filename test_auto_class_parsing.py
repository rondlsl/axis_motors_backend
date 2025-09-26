#!/usr/bin/env python3
"""
Тестовый скрипт для проверки парсинга auto_class
"""

def test_auto_class_parsing():
    """Тестируем парсинг различных форматов auto_class"""
    
    test_cases = [
        '{"A, B, C"}',  # Ваш случай
        '{"A","B","C"}',  # С кавычками
        '{A, B, C}',  # Без кавычек
        '["A", "B", "C"]',  # JSON массив
        ['A', 'B', 'C'],  # Python список
        'A,B,C',  # Простая строка
        '{"A"}',  # Один элемент
        'A',  # Один элемент без скобок
    ]
    
    for auto_class in test_cases:
        print(f"\nТестируем: {auto_class} (тип: {type(auto_class)})")
        
        allowed_classes = []
        
        if isinstance(auto_class, list):
            allowed_classes = [str(c).strip().upper() for c in auto_class if c]
        elif isinstance(auto_class, str):
            raw = auto_class.strip()
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            # Убираем двойные кавычки и обрабатываем строку
            raw = raw.replace('"', '').replace("'", "")
            allowed_classes = [part.strip().upper() for part in raw.split(",") if part.strip()]
        
        print(f"Результат: {allowed_classes}")
        
        # Проверяем, что все классы валидные
        valid_classes = ['A', 'B', 'C']
        valid_count = sum(1 for cls in allowed_classes if cls in valid_classes)
        print(f"Валидных классов: {valid_count}/{len(allowed_classes)}")

if __name__ == "__main__":
    test_auto_class_parsing()
