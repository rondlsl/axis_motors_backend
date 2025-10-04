"""
Модуль для инициализации тестовых данных
"""
import os
from sqlalchemy.orm import Session
from app.models.car_model import Car, CarBodyType, CarAutoClass, CarStatus
from app.models.user_model import User, UserRole


def init_test_data(db: Session) -> None:
    """
    Инициализирует тестовые данные: пользователей и автомобили
    """
    try:
        # Создаем владельца
        owner = create_owner(db)
        
        # Создаем автомобили
        create_cars(db, owner)
        
        # Создаем механика
        create_mechanic(db)
        
        # Создаем других пользователей
        create_system_users(db)
        
        # Создаем моковые автомобили
        create_mock_cars(db, owner)
        
        print("✅ Все тестовые данные успешно инициализированы")
        
    except Exception as e:
        print(f"❌ Ошибка при инициализации тестовых данных: {e}")
        raise


def create_owner(db: Session) -> User:
    """Создает владельца автомобилей"""
    owner_phone = "77000250400"
    owner = db.query(User).filter(User.phone_number == owner_phone).first()
    
    if not owner:
        owner = User(
            phone_number=owner_phone, 
            role=UserRole.CLIENT, 
            wallet_balance=0
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        print("✅ Владелец создан")
    else:
        print("ℹ️ Владелец уже существует")
    
    return owner


def create_cars(db: Session, owner: User) -> None:
    """Создает автомобили"""
    
    cars_to_create = []
    
    # HAVAL F7x
    if not db.query(Car).filter(Car.id == 1).first():
        car1 = Car(
            id=1,
            name="HAVAL F7x",
            gps_id="800153076",
            gps_imei="866011056063951",
            engine_volume=2.0,
            year=2021,
            drive_type=3,
            price_per_minute=70,
            price_per_hour=3125,
            price_per_day=50000,
            plate_number="422ABK02",
            latitude=43.238949,
            longitude=76.889709,
            fuel_level=80,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            course=90,
            description="Машина в идеальном состоянии.",
            photos=get_car_photos(1)
        )
        cars_to_create.append(("HAVAL F7x (id=1)", car1))
    else:
        print("ℹ️ HAVAL F7x (id=1) уже существует")

    # MB CLA45s
    if not db.query(Car).filter(Car.id == 2).first():
        car2 = Car(
            id=2,
            name="MB CLA45s",
            gps_id="800212421",
            gps_imei="869132074567851",
            engine_volume=2.0,
            year=2019,
            drive_type=3,
            price_per_minute=140,
            price_per_hour=5600,
            price_per_day=100000,
            plate_number="666AZV02",
            latitude=43.224048,
            longitude=76.961871,
            fuel_level=40,
            course=23,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            description="Разбита левая передняя фара. Разбит задний правый фонарь. Вмятина и царапина на правой задней двери.",
            photos=get_car_photos(2)
        )
        cars_to_create.append(("MB CLA45s (id=2)", car2))
    else:
        print("ℹ️ MB CLA45s (id=2) уже существует")

    # Hongqi e-qm5
    if not db.query(Car).filter(Car.id == 3).first():
        car3 = Car(
            id=3,
            name="Hongqi e-qm5",
            gps_id="800283232",
            gps_imei="869132074464026",
            engine_volume=0.0,  # Электромобиль
            year=2025,
            drive_type=3,
            price_per_minute=70,
            price_per_hour=3125,
            price_per_day=50000,
            plate_number="890AVB09",
            latitude=43.250000,
            longitude=76.950000,
            fuel_level=100,  
            body_type=CarBodyType.ELECTRIC,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            course=0,
            description="Электромобиль в отличном состоянии.",
            photos=get_car_photos(3)
        )
        cars_to_create.append(("Hongqi e-qm5 (id=3)", car3))
    else:
        print("ℹ️ Hongqi e-qm5 (id=3) уже существует")
    
    # Добавляем все автомобили одним commit'ом
    if cars_to_create:
        for name, car in cars_to_create:
            db.add(car)
            print(f"✅ {name} добавлена")
        db.commit()


def create_mechanic(db: Session) -> None:
    """Создает механика"""
    mechanic_phone = "77007007070"
    mechanic = db.query(User).filter(User.phone_number == mechanic_phone).first()
    
    if not mechanic:
        mechanic = User(
            phone_number=mechanic_phone, 
            role=UserRole.MECHANIC, 
            wallet_balance=0
        )
        db.add(mechanic)
        db.commit()
        db.refresh(mechanic)
        print("✅ Механик создан")
    else:
        print("ℹ️ Механик уже существует")


def create_system_users(db: Session) -> None:
    """Создает системных пользователей (финансист, МВД)"""
    
    # Финансист
    financier_phone = "77777777771"
    financier = db.query(User).filter(User.phone_number == financier_phone).first()
    if not financier:
        financier = User(
            phone_number=financier_phone,
            first_name="Financier",
            last_name="Financier",
            role=UserRole.FINANCIER,
            documents_verified=True,
            is_active=True,
        )
        db.add(financier)
        db.commit()
        db.refresh(financier)
        print("✅ Финансист создан")
    else:
        print("ℹ️ Финансист уже существует")

    # МВД
    mvd_phone = "77777777772"
    mvd_user = db.query(User).filter(User.phone_number == mvd_phone).first()
    if not mvd_user:
        mvd_user = User(
            phone_number=mvd_phone,
            first_name="MVD",
            last_name="MVD",
            role=UserRole.MVD,
            documents_verified=True,
            is_active=True,
        )
        db.add(mvd_user)
        db.commit()
        db.refresh(mvd_user)
        print("✅ Пользователь МВД создан")
    else:
        print("ℹ️ Пользователь МВД уже существует")


def create_mock_cars(db: Session, owner: User) -> None:
    """Создает моковые автомобили со статусом OCCUPIED"""
    
    mock_cars_to_create = []
    
    # Bentley Flying Spur
    if not db.query(Car).filter(Car.id == 4).first():
        car4 = Car(
            id=4,
            name="Bentley Flying Spur",
            plate_number="001BEN01",
            latitude=43.200000,
            longitude=76.900000,
            gps_id=None,  # Нет GPS - моковый автомобиль
            gps_imei=None,  # Нет GPS - моковый автомобиль
            fuel_level=85,
            course=45,
            price_per_minute=200,
            price_per_hour=10000,
            price_per_day=200000,
            engine_volume=6.0,
            year=2018,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,  # Занят - не отображается
            description="Роскошный седан Bentley в отличном состоянии."
        )
        mock_cars_to_create.append(("Bentley Flying Spur (id=4)", car4))
    else:
        print("ℹ️ Bentley Flying Spur (id=4) уже существует")

    # Hyundai Palisade
    if not db.query(Car).filter(Car.id == 5).first():
        car5 = Car(
            id=5,
            name="Hyundai Palisade",
            plate_number="002HYU01",
            latitude=43.220000,
            longitude=76.920000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=90,
            price_per_minute=80,
            price_per_hour=4000,
            price_per_day=80000,
            engine_volume=3.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный внедорожник Hyundai для всей семьи."
        )
        mock_cars_to_create.append(("Hyundai Palisade (id=5)", car5))
    else:
        print("ℹ️ Hyundai Palisade (id=5) уже существует")

    # Mercedes CLA 45s (второй)
    if not db.query(Car).filter(Car.id == 6).first():
        car6 = Car(
            id=6,
            name="Mercedes CLA 45s",
            plate_number="003MER01",
            latitude=43.240000,
            longitude=76.940000,
            gps_id=None,
            gps_imei=None,
            fuel_level=60,
            course=180,
            price_per_minute=120,
            price_per_hour=6000,
            price_per_day=120000,
            engine_volume=2.0,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан Mercedes с мощным двигателем."
        )
        mock_cars_to_create.append(("Mercedes CLA 45s (id=6)", car6))
    else:
        print("ℹ️ Mercedes CLA 45s (id=6) уже существует")

    # ZEEKR 001
    if not db.query(Car).filter(Car.id == 7).first():
        car7 = Car(
            id=7,
            name="ZEEKR 001",
            plate_number="004ZEE01",
            latitude=43.260000,
            longitude=76.960000,
            gps_id=None,
            gps_imei=None,
            fuel_level=100,  # Электромобиль
            course=270,
            price_per_minute=90,
            price_per_hour=4500,
            price_per_day=90000,
            engine_volume=0.0,  # Электромобиль
            year=2023,
            drive_type=3,
            body_type=CarBodyType.ELECTRIC,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный электромобиль ZEEKR с передовыми технологиями."
        )
        mock_cars_to_create.append(("ZEEKR 001 (id=7)", car7))
    else:
        print("ℹ️ ZEEKR 001 (id=7) уже существует")

    # Hongqi E-QM5 (второй)
    if not db.query(Car).filter(Car.id == 8).first():
        car8 = Car(
            id=8,
            name="Hongqi E-QM5",
            plate_number="005HON01",
            latitude=43.280000,
            longitude=76.980000,
            gps_id=None,
            gps_imei=None,
            fuel_level=100,  # Электромобиль
            course=315,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=0.0,  # Электромобиль
            year=2025,
            drive_type=3,
            body_type=CarBodyType.ELECTRIC,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Новейший электромобиль Hongqi 2025 года."
        )
        mock_cars_to_create.append(("Hongqi E-QM5 (id=8)", car8))
    else:
        print("ℹ️ Hongqi E-QM5 (id=8) уже существует")

    # Toyota Land Cruiser Prado
    if not db.query(Car).filter(Car.id == 9).first():
        car9 = Car(
            id=9,
            name="Toyota Land Cruiser Prado",
            plate_number="006TOY01",
            latitude=43.300000,
            longitude=77.000000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=135,
            price_per_minute=100,
            price_per_hour=5000,
            price_per_day=100000,
            engine_volume=2.7,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный внедорожник Toyota для любых дорог."
        )
        mock_cars_to_create.append(("Toyota Land Cruiser Prado (id=9)", car9))
    else:
        print("ℹ️ Toyota Land Cruiser Prado (id=9) уже существует")
    
    # Добавляем все моковые автомобили одним commit'ом
    if mock_cars_to_create:
        for name, car in mock_cars_to_create:
            db.add(car)
            print(f"✅ {name} добавлен (моковый)")
        db.commit()


def get_car_photos(car_id: int) -> list[str]:
    """Получает список фотографий автомобиля из папки uploads/cars/{car_id}"""
    photos_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "cars", str(car_id))
    photos = []
    
    if os.path.isdir(photos_dir):
        for fname in sorted(os.listdir(photos_dir)):
            if os.path.isfile(os.path.join(photos_dir, fname)):
                photos.append(f"/uploads/cars/{car_id}/{fname}")
    
    return photos
