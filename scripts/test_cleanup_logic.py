#!/usr/bin/env python3
"""
Тест для демонстрации логики очистки файлов.
"""

def demonstrate_cleanup_logic():
    """Демонстрация работы логики очистки."""
    
    print("🧪 Демонстрация логики очистки MinIO")
    print("=" * 50)
    
    # Пример структуры папок в MinIO
    minio_structure = {
        'cars/abc123': {
            'jpeg': {'cars/abc123/photo1.jpg', 'cars/abc123/photo2.jpg'},
            'webp': {'cars/abc123/photo1.webp', 'cars/abc123/photo2.webp'}
        },
        'users/avatars': {
            'jpeg': {'users/avatars/user1.jpg'},
            'webp': set()
        },
        'uploads/temp': {
            'jpeg': {'uploads/temp/temp1.jpg', 'uploads/temp/temp2.jpg'},
            'webp': set()
        },
        'supports/tickets': {
            'jpeg': {'supports/tickets/proof.jpg'},
            'webp': {'supports/tickets/proof.webp'}
        }
    }
    
    # Файлы в БД
    db_files = {
        'jpeg': {'cars/abc123/photo1.jpg', 'users/avatars/user1.jpg'},
        'webp': {'cars/abc123/photo1.webp', 'supports/tickets/proof.webp'},
        'all': {'cars/abc123/photo1.jpg', 'users/avatars/user1.jpg', 'cars/abc123/photo1.webp', 'supports/tickets/proof.webp'}
    }
    
    print("📁 Структура папок в MinIO:")
    for folder, data in minio_structure.items():
        print(f"\n📂 {folder}:")
        print(f"   JPEG: {len(data['jpeg'])} файлов")
        for jpeg in sorted(data['jpeg']):
            status = "✅ в БД" if jpeg in db_files['jpeg'] else "❌ не в БД"
            print(f"     - {jpeg} ({status})")
        print(f"   WebP: {len(data['webp'])} файлов")
        for webp in sorted(data['webp']):
            status = "✅ в БД" if webp in db_files['webp'] else "❌ не в БД"
            print(f"     - {webp} ({status})")
    
    print("\n🔍 Логика удаления:")
    files_to_delete = set()
    
    for folder_name, folder_data in minio_structure.items():
        # Пропускаем папку supports
        if folder_name.startswith('supports/'):
            print(f"⏭️  Пропускаем папку {folder_name} (защищена)")
            continue
            
        jpeg_files = folder_data['jpeg']
        webp_files = folder_data['webp']
        
        if not jpeg_files:
            continue
        
        print(f"\n📂 Папка {folder_name}:")
        
        # Проверяем есть ли WebP файлы из этой же папки в БД
        webp_in_db = set()
        for webp_path in webp_files:
            if webp_path in db_files['webp']:
                webp_in_db.add(webp_path)
        
        if webp_in_db:
            print(f"   🎯 Найдены WebP в БД: {len(webp_in_db)}")
            print(f"   ➡️  Удаляем все JPEG которых нет в БД")
            
            for jpeg_file in jpeg_files:
                if jpeg_file not in db_files['jpeg']:
                    files_to_delete.add(jpeg_file)
                    print(f"     🗑️  {jpeg_file} (WebP есть в БД)")
                else:
                    print(f"     ✅ {jpeg_file} (есть в БД)")
        else:
            print(f"   ❌ WebP в БД не найдены")
            print(f"   ➡️  Удаляем только JPEG которых нет в БД")
            
            for jpeg_file in jpeg_files:
                if jpeg_file not in db_files['jpeg']:
                    files_to_delete.add(jpeg_file)
                    print(f"     🗑️  {jpeg_file} (не в БД)")
                else:
                    print(f"     ✅ {jpeg_file} (есть в БД)")
    
    print("\n📊 Итог:")
    print(f"   Всего JPEG файлов: {sum(len(data['jpeg']) for data in minio_structure.values())}")
    print(f"   К удалению: {len(files_to_delete)}")
    print(f"   Процент удаления: {len(files_to_delete) / sum(len(data['jpeg']) for data in minio_structure.values()) * 100:.1f}%")
    
    if files_to_delete:
        print("\n🗑️  Файлы для удаления:")
        for file in sorted(files_to_delete):
            print(f"   - {file}")
    
    print("\n✅ Логика работы продемонстрирована!")

if __name__ == "__main__":
    demonstrate_cleanup_logic()
