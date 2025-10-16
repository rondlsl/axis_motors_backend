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
    owner_iin = "980601523456" 
    owner = db.query(User).filter(User.phone_number == owner_phone).first()
    
    if not owner:
        owner = User(
            phone_number=owner_phone, 
            role=UserRole.CLIENT, 
            wallet_balance=0,
            iin=owner_iin
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        print("✅ Владелец создан")
    else:
        print("ℹ️ Владелец уже существует")
    
    return owner


def create_cars(db: Session, owner: User) -> None:
    """Создает автомобили (UUID id). Сопоставление по уникальному plate_number, без ручного задания id)."""
    specs = [
        {
            "name": "HAVAL F7x",
            "gps_id": "800153076",
            "gps_imei": "866011056063951",
            "engine_volume": 2.0,
            "year": 2021,
            "drive_type": 3,
            "price_per_minute": 70,
            "price_per_hour": 3125,
            "price_per_day": 50000,
            "plate_number": "422ABK02",
            "latitude": 43.238949,
            "longitude": 76.889709,
            "fuel_level": 80,
            "body_type": CarBodyType.CROSSOVER,
            "auto_class": CarAutoClass.A,
            "course": 90,
            "description": "Машина в идеальном состоянии.",
            "photos": get_car_photos(1),
        },
        {
            "name": "MB CLA45s",
            "gps_id": "800212421",
            "gps_imei": "860803068143045",
            "engine_volume": 2.0,
            "year": 2019,
            "drive_type": 3,
            "price_per_minute": 140,
            "price_per_hour": 5600,
            "price_per_day": 100000,
            "plate_number": "666AZV02",
            "latitude": 43.224048,
            "longitude": 76.961871,
            "fuel_level": 40,
            "course": 23,
            "body_type": CarBodyType.SEDAN,
            "auto_class": CarAutoClass.B,
            "description": "Разбита левая передняя фара. Разбит задний правый фонарь. Вмятина и царапина на правой задней двери.",
            "photos": get_car_photos(2),
        },
        {
            "name": "Hongqi e-qm5",
            "gps_id": "800283232",
            "gps_imei": "860803068139548",
            "engine_volume": 0.0,
            "year": 2025,
            "drive_type": 3,
            "price_per_minute": 70,
            "price_per_hour": 3125,
            "price_per_day": 50000,
            "plate_number": "890AVB09",
            "latitude": 43.25,
            "longitude": 76.95,
            "fuel_level": 100,
            "body_type": CarBodyType.ELECTRIC,
            "auto_class": CarAutoClass.A,
            "course": 0,
            "description": "Электромобиль в отличном состоянии.",
            "photos": get_car_photos(3),
        },
    ]

    created = 0
    for spec in specs:
        plate = spec["plate_number"]
        existing = db.query(Car).filter(Car.plate_number == plate).first()
        if existing:
            print(f"ℹ️ {spec['name']} ({plate}) уже существует")
            continue
        car = Car(**spec, owner_id=owner.id)
        db.add(car)
        created += 1
        print(f"✅ {spec['name']} ({plate}) добавлена")
    if created:
        db.commit()


def create_mechanic(db: Session) -> None:
    """Создает механика"""
    mechanic_phone = "71234567890"
    mechanic_iin = "950301523456" 
    mechanic = db.query(User).filter(User.phone_number == mechanic_phone).first()
    
    if not mechanic:
        mechanic = User(
            phone_number=mechanic_phone,
            first_name="Механик",
            last_name="Механик",
            role=UserRole.MECHANIC, 
            wallet_balance=0,
            iin=mechanic_iin
        )
        db.add(mechanic)
        db.commit()
        db.refresh(mechanic)
        print("✅ Механик создан")
    else:
        print("ℹ️ Механик уже существует")
        # Обновляем имена если они отсутствуют
        if not mechanic.first_name or not mechanic.last_name:
            mechanic.first_name = "Механик"
            mechanic.last_name = "Механик"
            db.commit()
            print("✅ Имена механика обновлены")


def create_system_users(db: Session) -> None:
    """Создает системных пользователей (финансист, МВД)"""
    
    # Финансист
    financier_phone = "77777777771"
    financier_iin = "970401523457"  
    financier = db.query(User).filter(User.phone_number == financier_phone).first()
    if not financier:
        financier = User(
            phone_number=financier_phone,
            first_name="Financier",
            last_name="Financier",
            role=UserRole.FINANCIER,
            documents_verified=True,
            is_active=True,
            iin=financier_iin,
        )
        db.add(financier)
        db.commit()
        db.refresh(financier)
        print("✅ Финансист создан")
    else:
        print("ℹ️ Финансист уже существует")

    # МВД
    mvd_phone = "77777777772"
    mvd_iin = "970205558210"  
    mvd_user = db.query(User).filter(User.phone_number == mvd_phone).first()
    if not mvd_user:
        mvd_user = User(
            phone_number=mvd_phone,
            first_name="MVD",
            last_name="MVD",
            role=UserRole.MVD,
            documents_verified=True,
            is_active=True,
            iin=mvd_iin,
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
    if not db.query(Car).filter(Car.plate_number == "x4").first():
        car4 = Car(
            name="Bentley Flying Spur",
            plate_number="x4",
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
        car4.photos = get_car_photos(4)
        mock_cars_to_create.append(("Bentley Flying Spur", car4))
    else:
        print("ℹ️ Bentley Flying Spur уже существует")

    # Hyundai Palisade
    if not db.query(Car).filter(Car.plate_number == "x5").first():
        car5 = Car(
            name="Hyundai Palisade",
            plate_number="x5",
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
        car5.photos = get_car_photos(5)
        mock_cars_to_create.append(("Hyundai Palisade", car5))
    else:
        print("ℹ️ Hyundai Palisade уже существует")

    # Mercedes CLA 45s (второй)
    if not db.query(Car).filter(Car.plate_number == "x6").first():
        car6 = Car(
            name="Mercedes CLA 45s",
            plate_number="x6",
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
        car6.photos = get_car_photos(6)
        mock_cars_to_create.append(("Mercedes CLA 45s", car6))
    else:
        print("ℹ️ Mercedes CLA 45s уже существует")

    # ZEEKR 001
    if not db.query(Car).filter(Car.plate_number == "x7").first():
        car7 = Car(
            name="ZEEKR 001",
            plate_number="x7",
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
        car7.photos = get_car_photos(7)
        mock_cars_to_create.append(("ZEEKR 001", car7))
    else:
        print("ℹ️ ZEEKR 001 уже существует")

    # Hongqi E-QM5 (второй)
    if not db.query(Car).filter(Car.plate_number == "x8").first():
        car8 = Car(
            name="Hongqi E-QM5",
            plate_number="x8",
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
        car8.photos = get_car_photos(8)
        mock_cars_to_create.append(("Hongqi E-QM5", car8))
    else:
        print("ℹ️ Hongqi E-QM5 уже существует")

    # Toyota Land Cruiser Prado
    if not db.query(Car).filter(Car.plate_number == "x9").first():
        car9 = Car(
            name="Toyota Land Cruiser Prado",
            plate_number="x9",
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
        car9.photos = get_car_photos(9)
        mock_cars_to_create.append(("Toyota Land Cruiser Prado", car9))
    else:
        print("ℹ️ Toyota Land Cruiser Prado уже существует")
    
    # Range Rover Sport
    if not db.query(Car).filter(Car.plate_number == "x10").first():
        car10 = Car(
            name="Range Rover Sport",
            plate_number="x10",
            latitude=43.310000,
            longitude=77.010000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=45,
            price_per_minute=100,
            price_per_hour=5000,
            price_per_day=100000,
            engine_volume=3.0,
            year=2017,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный внедорожник Range Rover Sport."
        )
        car10.photos = get_car_photos(10)
        mock_cars_to_create.append(("Range Rover Sport", car10))
    else:
        print("ℹ️ Range Rover Sport уже существует")

    # Mercedes e63s
    if not db.query(Car).filter(Car.plate_number == "x11").first():
        car11 = Car(
            name="Mercedes e63s",
            plate_number="x11",
            latitude=43.320000,
            longitude=77.020000,
            gps_id=None,
            gps_imei=None,
            fuel_level=60,
            course=90,
            price_per_minute=120,
            price_per_hour=6000,
            price_per_day=120000,
            engine_volume=4.0,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан Mercedes e63s."
        )
        car11.photos = get_car_photos(11)
        mock_cars_to_create.append(("Mercedes e63s", car11))
    else:
        print("ℹ️ Mercedes e63s уже существует")

    # Toyota Camry 2020
    if not db.query(Car).filter(Car.plate_number == "x12").first():
        car12 = Car(
            name="Toyota Camry",
            plate_number="x12",
            latitude=43.330000,
            longitude=77.030000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=135,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.5,
            year=2020,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный седан Toyota Camry."
        )
        car12.photos = get_car_photos(12)
        mock_cars_to_create.append(("Toyota Camry 2020", car12))
    else:
        print("ℹ️ Toyota Camry 2020 уже существует")

    # BMW m5
    if not db.query(Car).filter(Car.plate_number == "x13").first():
        car13 = Car(
            name="BMW m5",
            plate_number="x13",
            latitude=43.340000,
            longitude=77.040000,
            gps_id=None,
            gps_imei=None,
            fuel_level=65,
            course=180,
            price_per_minute=130,
            price_per_hour=6500,
            price_per_day=130000,
            engine_volume=4.4,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан BMW m5."
        )
        car13.photos = get_car_photos(13)
        mock_cars_to_create.append(("BMW m5", car13))
    else:
        print("ℹ️ BMW m5 уже существует")

    # Toyota Highlander
    if not db.query(Car).filter(Car.plate_number == "x14").first():
        car14 = Car(
            name="Toyota Highlander",
            plate_number="x14",
            latitude=43.350000,
            longitude=77.050000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=225,
            price_per_minute=90,
            price_per_hour=4500,
            price_per_day=90000,
            engine_volume=3.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный кроссовер Toyota Highlander."
        )
        car14.photos = get_car_photos(14)
        mock_cars_to_create.append(("Toyota Highlander", car14))
    else:
        print("ℹ️ Toyota Highlander уже существует")

    # Lexus es 350
    if not db.query(Car).filter(Car.plate_number == "x15").first():
        car15 = Car(
            name="Lexus es 350",
            plate_number="x15",
            latitude=43.360000,
            longitude=77.060000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=110,
            price_per_hour=5500,
            price_per_day=110000,
            engine_volume=3.5,
            year=2023,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Lexus es 350."
        )
        car15.photos = get_car_photos(15)
        mock_cars_to_create.append(("Lexus es 350", car15))
    else:
        print("ℹ️ Lexus es 350 уже существует")

    # Toyota Camry 2024
    if not db.query(Car).filter(Car.plate_number == "x16").first():
        car16 = Car(
            name="Toyota Camry",
            plate_number="x16",
            latitude=43.370000,
            longitude=77.070000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=315,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=2.5,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Новейший седан Toyota Camry 2024."
        )
        car16.photos = get_car_photos(16)
        mock_cars_to_create.append(("Toyota Camry 2024", car16))
    else:
        print("ℹ️ Toyota Camry 2024 уже существует")

    # BMW 540i 2018
    if not db.query(Car).filter(Car.plate_number == "x17").first():
        car17 = Car(
            name="BMW 540i",
            plate_number="x17",
            latitude=43.380000,
            longitude=77.080000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=0,
            price_per_minute=100,
            price_per_hour=5000,
            price_per_day=100000,
            engine_volume=3.0,
            year=2018,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан BMW 540i."
        )
        car17.photos = get_car_photos(17)
        mock_cars_to_create.append(("BMW 540i 2018", car17))
    else:
        print("ℹ️ BMW 540i 2018 уже существует")

    # Lexus rx 350h
    if not db.query(Car).filter(Car.plate_number == "x18").first():
        car18 = Car(
            name="Lexus rx 350h",
            plate_number="x18",
            latitude=43.390000,
            longitude=77.090000,
            gps_id=None,
            gps_imei=None,
            fuel_level=85,
            course=45,
            price_per_minute=95,
            price_per_hour=4750,
            price_per_day=95000,
            engine_volume=2.4,
            year=2025,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Гибридный кроссовер Lexus rx 350h."
        )
        car18.photos = get_car_photos(18)
        mock_cars_to_create.append(("Lexus rx 350h", car18))
    else:
        print("ℹ️ Lexus rx 350h уже существует")

    # Changan uni-v
    if not db.query(Car).filter(Car.plate_number == "x19").first():
        car19 = Car(
            name="Changan uni-v",
            plate_number="x19",
            latitude=43.400000,
            longitude=77.100000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=90,
            price_per_minute=60,
            price_per_hour=3000,
            price_per_day=60000,
            engine_volume=1.5,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Компактный седан Changan uni-v."
        )
        car19.photos = get_car_photos(19)
        mock_cars_to_create.append(("Changan uni-v", car19))
    else:
        print("ℹ️ Changan uni-v уже существует")

    # Lexus es 300h
    if not db.query(Car).filter(Car.plate_number == "x20").first():
        car20 = Car(
            name="Lexus es 300h",
            plate_number="x20",
            latitude=43.410000,
            longitude=77.110000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=135,
            price_per_minute=105,
            price_per_hour=5250,
            price_per_day=105000,
            engine_volume=2.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Гибридный седан Lexus es 300h."
        )
        car20.photos = get_car_photos(20)
        mock_cars_to_create.append(("Lexus es 300h", car20))
    else:
        print("ℹ️ Lexus es 300h уже существует")

    # Kia k8
    if not db.query(Car).filter(Car.plate_number == "x21").first():
        car21 = Car(
            name="Kia k8",
            plate_number="x21",
            latitude=43.420000,
            longitude=77.120000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=180,
            price_per_minute=85,
            price_per_hour=4250,
            price_per_day=85000,
            engine_volume=3.5,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Kia k8."
        )
        car21.photos = get_car_photos(21)
        mock_cars_to_create.append(("Kia k8", car21))
    else:
        print("ℹ️ Kia k8 уже существует")

    # Toyota Camry 2024 (второй)
    if not db.query(Car).filter(Car.plate_number == "x22").first():
        car22 = Car(
            name="Toyota Camry",
            plate_number="x22",
            latitude=43.430000,
            longitude=77.130000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=225,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=2.5,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Новейший седан Toyota Camry 2024 (второй)."
        )
        car22.photos = get_car_photos(22)
        mock_cars_to_create.append(("Toyota Camry 2024 второй", car22))
    else:
        print("ℹ️ Toyota Camry 2024 второй уже существует")

    # Hyundai Palisade
    if not db.query(Car).filter(Car.plate_number == "x23").first():
        car23 = Car(
            name="Hyundai Palisade",
            plate_number="x23",
            latitude=43.440000,
            longitude=77.140000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=90,
            price_per_hour=4500,
            price_per_day=90000,
            engine_volume=3.8,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный внедорожник Hyundai Palisade."
        )
        car23.photos = get_car_photos(23)
        mock_cars_to_create.append(("Hyundai Palisade", car23))
    else:
        print("ℹ️ Hyundai Palisade уже существует")

    # Mercedes e200
    if not db.query(Car).filter(Car.plate_number == "x24").first():
        car24 = Car(
            name="Mercedes e200",
            plate_number="x24",
            latitude=43.450000,
            longitude=77.150000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=315,
            price_per_minute=80,
            price_per_hour=4000,
            price_per_day=80000,
            engine_volume=2.0,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Элегантный седан Mercedes e200."
        )
        car24.photos = get_car_photos(24)
        mock_cars_to_create.append(("Mercedes e200", car24))
    else:
        print("ℹ️ Mercedes e200 уже существует")

    # Mercedes s63
    if not db.query(Car).filter(Car.plate_number == "x25").first():
        car25 = Car(
            name="Mercedes s63",
            plate_number="x25",
            latitude=43.460000,
            longitude=77.160000,
            gps_id=None,
            gps_imei=None,
            fuel_level=65,
            course=0,
            price_per_minute=140,
            price_per_hour=7000,
            price_per_day=140000,
            engine_volume=4.0,
            year=2017,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Роскошный седан Mercedes s63."
        )
        car25.photos = get_car_photos(25)
        mock_cars_to_create.append(("Mercedes s63", car25))
    else:
        print("ℹ️ Mercedes s63 уже существует")

    # Hyundai Tucson
    if not db.query(Car).filter(Car.plate_number == "x26").first():
        car26 = Car(
            name="Hyundai Tucson",
            plate_number="x26",
            latitude=43.470000,
            longitude=77.170000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=45,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=2.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный кроссовер Hyundai Tucson."
        )
        car26.photos = get_car_photos(26)
        mock_cars_to_create.append(("Hyundai Tucson", car26))
    else:
        print("ℹ️ Hyundai Tucson уже существует")

    # Changan uni-k
    if not db.query(Car).filter(Car.plate_number == "x27").first():
        car27 = Car(
            name="Changan uni-k",
            plate_number="x27",
            latitude=43.480000,
            longitude=77.180000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=90,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.0,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Компактный кроссовер Changan uni-k."
        )
        car27.photos = get_car_photos(27)
        mock_cars_to_create.append(("Changan uni-k", car27))
    else:
        print("ℹ️ Changan uni-k уже существует")

    # ZEEKR 001 (второй)
    if not db.query(Car).filter(Car.plate_number == "x28").first():
        car28 = Car(
            name="ZEEKR 001",
            plate_number="x28",
            latitude=43.490000,
            longitude=77.190000,
            gps_id=None,
            gps_imei=None,
            fuel_level=100,
            course=135,
            price_per_minute=90,
            price_per_hour=4500,
            price_per_day=90000,
            engine_volume=0.0,
            year=2023,
            drive_type=3,
            body_type=CarBodyType.ELECTRIC,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный электромобиль ZEEKR 001 (второй)."
        )
        car28.photos = get_car_photos(28)
        mock_cars_to_create.append(("ZEEKR 001 второй", car28))
    else:
        print("ℹ️ ZEEKR 001 второй уже существует")

    # Toyota Land Cruiser 2018
    if not db.query(Car).filter(Car.plate_number == "x29").first():
        car29 = Car(
            name="Toyota Land Cruiser",
            plate_number="x29",
            latitude=43.500000,
            longitude=77.200000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=180,
            price_per_minute=110,
            price_per_hour=5500,
            price_per_day=110000,
            engine_volume=4.6,
            year=2018,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Легендарный внедорожник Toyota Land Cruiser."
        )
        car29.photos = get_car_photos(29)
        mock_cars_to_create.append(("Toyota Land Cruiser 2018", car29))
    else:
        print("ℹ️ Toyota Land Cruiser 2018 уже существует")

    # BMW 540i 2024 
    if not db.query(Car).filter(Car.plate_number == "x30").first():
        car30 = Car(
            name="BMW 540i",
            plate_number="x30",
            latitude=43.520000,
            longitude=77.220000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=105,
            price_per_hour=5250,
            price_per_day=105000,
            engine_volume=3.0,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан BMW 540i 2024."
        )
        car30.photos = get_car_photos(30)
        mock_cars_to_create.append(("BMW 540i 2024", car30))
    else:
        print("ℹ️ BMW 540i 2024 уже существует")

    # Добавляем все моковые автомобили одним commit'ом
    if mock_cars_to_create:
        for name, car in mock_cars_to_create:
            db.add(car)
            print(f"✅ {name} добавлен (моковый)")
        db.commit()


def get_car_photos(car_id: str) -> list[str]:
    """Получает список фотографий автомобиля из папки uploads/cars/{car_id}"""
    photos_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "cars", str(car_id))
    photos = []
    
    if os.path.isdir(photos_dir):
        for fname in sorted(os.listdir(photos_dir)):
            if os.path.isfile(os.path.join(photos_dir, fname)):
                photos.append(f"/uploads/cars/{car_id}/{fname}")
    
    return photos
