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
            gps_imei="860803068143045",
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
            gps_imei="860803068139548",
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
    mechanic_phone = "71234567890"
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
            plate_number="x",
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
        car4.plate_number = f"x{car4.id}"
        mock_cars_to_create.append(("Bentley Flying Spur (id=4)", car4))
    else:
        print("ℹ️ Bentley Flying Spur (id=4) уже существует")

    # Hyundai Palisade
    if not db.query(Car).filter(Car.id == 5).first():
        car5 = Car(
            id=5,
            name="Hyundai Palisade",
            plate_number="x",
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
        car5.plate_number = f"x{car5.id}"
        mock_cars_to_create.append(("Hyundai Palisade (id=5)", car5))
    else:
        print("ℹ️ Hyundai Palisade (id=5) уже существует")

    # Mercedes CLA 45s (второй)
    if not db.query(Car).filter(Car.id == 6).first():
        car6 = Car(
            id=6,
            name="Mercedes CLA 45s",
            plate_number="x",
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
        car6.plate_number = f"x{car6.id}"
        mock_cars_to_create.append(("Mercedes CLA 45s (id=6)", car6))
    else:
        print("ℹ️ Mercedes CLA 45s (id=6) уже существует")

    # ZEEKR 001
    if not db.query(Car).filter(Car.id == 7).first():
        car7 = Car(
            id=7,
            name="ZEEKR 001",
            plate_number="x",
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
        car7.plate_number = f"x{car7.id}"
        mock_cars_to_create.append(("ZEEKR 001 (id=7)", car7))
    else:
        print("ℹ️ ZEEKR 001 (id=7) уже существует")

    # Hongqi E-QM5 (второй)
    if not db.query(Car).filter(Car.id == 8).first():
        car8 = Car(
            id=8,
            name="Hongqi E-QM5",
            plate_number="x",
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
        car8.plate_number = f"x{car8.id}"
        mock_cars_to_create.append(("Hongqi E-QM5 (id=8)", car8))
    else:
        print("ℹ️ Hongqi E-QM5 (id=8) уже существует")

    # Toyota Land Cruiser Prado
    if not db.query(Car).filter(Car.id == 9).first():
        car9 = Car(
            id=9,
            name="Toyota Land Cruiser Prado",
            plate_number="x",
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
        car9.plate_number = f"x{car9.id}"
        mock_cars_to_create.append(("Toyota Land Cruiser Prado (id=9)", car9))
    else:
        print("ℹ️ Toyota Land Cruiser Prado (id=9) уже существует")
    
    # Range Rover Sport
    if not db.query(Car).filter(Car.id == 10).first():
        car10 = Car(
            id=10,
            name="Range Rover Sport",
            plate_number="x",
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
        car10.plate_number = f"x{car10.id}"
        mock_cars_to_create.append(("Range Rover Sport (id=10)", car10))
    else:
        print("ℹ️ Range Rover Sport (id=10) уже существует")

    # Mercedes e63s
    if not db.query(Car).filter(Car.id == 11).first():
        car11 = Car(
            id=11,
            name="Mercedes e63s",
            plate_number="x",
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
        car11.plate_number = f"x{car11.id}"
        mock_cars_to_create.append(("Mercedes e63s (id=11)", car11))
    else:
        print("ℹ️ Mercedes e63s (id=11) уже существует")

    # Toyota Camry 2020
    if not db.query(Car).filter(Car.id == 12).first():
        car12 = Car(
            id=12,
            name="Toyota Camry",
            plate_number="x",
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
        car12.plate_number = f"x{car12.id}"
        mock_cars_to_create.append(("Toyota Camry 2020 (id=12)", car12))
    else:
        print("ℹ️ Toyota Camry 2020 (id=12) уже существует")

    # BMW m5
    if not db.query(Car).filter(Car.id == 13).first():
        car13 = Car(
            id=13,
            name="BMW m5",
            plate_number="x",
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
        car13.plate_number = f"x{car13.id}"
        mock_cars_to_create.append(("BMW m5 (id=13)", car13))
    else:
        print("ℹ️ BMW m5 (id=13) уже существует")

    # Toyota Highlander
    if not db.query(Car).filter(Car.id == 14).first():
        car14 = Car(
            id=14,
            name="Toyota Highlander",
            plate_number="x",
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
        car14.plate_number = f"x{car14.id}"
        mock_cars_to_create.append(("Toyota Highlander (id=14)", car14))
    else:
        print("ℹ️ Toyota Highlander (id=14) уже существует")

    # Lexus es 350
    if not db.query(Car).filter(Car.id == 15).first():
        car15 = Car(
            id=15,
            name="Lexus es 350",
            plate_number="x",
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
        car15.plate_number = f"x{car15.id}"
        mock_cars_to_create.append(("Lexus es 350 (id=15)", car15))
    else:
        print("ℹ️ Lexus es 350 (id=15) уже существует")

    # Toyota Camry 2024
    if not db.query(Car).filter(Car.id == 16).first():
        car16 = Car(
            id=16,
            name="Toyota Camry",
            plate_number="x",
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
        car16.plate_number = f"x{car16.id}"
        mock_cars_to_create.append(("Toyota Camry 2024 (id=16)", car16))
    else:
        print("ℹ️ Toyota Camry 2024 (id=16) уже существует")

    # BMW 540i 2018
    if not db.query(Car).filter(Car.id == 17).first():
        car17 = Car(
            id=17,
            name="BMW 540i",
            plate_number="x",
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
        car17.plate_number = f"x{car17.id}"
        mock_cars_to_create.append(("BMW 540i 2018 (id=17)", car17))
    else:
        print("ℹ️ BMW 540i 2018 (id=17) уже существует")

    # Lexus rx 350h
    if not db.query(Car).filter(Car.id == 18).first():
        car18 = Car(
            id=18,
            name="Lexus rx 350h",
            plate_number="x",
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
        car18.plate_number = f"x{car18.id}"
        mock_cars_to_create.append(("Lexus rx 350h (id=18)", car18))
    else:
        print("ℹ️ Lexus rx 350h (id=18) уже существует")

    # Changan uni-v
    if not db.query(Car).filter(Car.id == 19).first():
        car19 = Car(
            id=19,
            name="Changan uni-v",
            plate_number="x",
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
        car19.plate_number = f"x{car19.id}"
        mock_cars_to_create.append(("Changan uni-v (id=19)", car19))
    else:
        print("ℹ️ Changan uni-v (id=19) уже существует")

    # Lexus es 300h
    if not db.query(Car).filter(Car.id == 20).first():
        car20 = Car(
            id=20,
            name="Lexus es 300h",
            plate_number="x",
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
        car20.plate_number = f"x{car20.id}"
        mock_cars_to_create.append(("Lexus es 300h (id=20)", car20))
    else:
        print("ℹ️ Lexus es 300h (id=20) уже существует")

    # Kia k8
    if not db.query(Car).filter(Car.id == 21).first():
        car21 = Car(
            id=21,
            name="Kia k8",
            plate_number="x",
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
        car21.plate_number = f"x{car21.id}"
        mock_cars_to_create.append(("Kia k8 (id=21)", car21))
    else:
        print("ℹ️ Kia k8 (id=21) уже существует")

    # Toyota Camry 2024 (второй)
    if not db.query(Car).filter(Car.id == 22).first():
        car22 = Car(
            id=22,
            name="Toyota Camry",
            plate_number="x",
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
        car22.plate_number = f"x{car22.id}"
        mock_cars_to_create.append(("Toyota Camry 2024 второй (id=22)", car22))
    else:
        print("ℹ️ Toyota Camry 2024 второй (id=22) уже существует")

    # Hyundai Palisade
    if not db.query(Car).filter(Car.id == 23).first():
        car23 = Car(
            id=23,
            name="Hyundai Palisade",
            plate_number="x",
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
        car23.plate_number = f"x{car23.id}"
        mock_cars_to_create.append(("Hyundai Palisade (id=23)", car23))
    else:
        print("ℹ️ Hyundai Palisade (id=23) уже существует")

    # Mercedes e200
    if not db.query(Car).filter(Car.id == 24).first():
        car24 = Car(
            id=24,
            name="Mercedes e200",
            plate_number="x",
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
        car24.plate_number = f"x{car24.id}"
        mock_cars_to_create.append(("Mercedes e200 (id=24)", car24))
    else:
        print("ℹ️ Mercedes e200 (id=24) уже существует")

    # Mercedes s63
    if not db.query(Car).filter(Car.id == 25).first():
        car25 = Car(
            id=25,
            name="Mercedes s63",
            plate_number="x",
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
        car25.plate_number = f"x{car25.id}"
        mock_cars_to_create.append(("Mercedes s63 (id=25)", car25))
    else:
        print("ℹ️ Mercedes s63 (id=25) уже существует")

    # Hyundai Tucson
    if not db.query(Car).filter(Car.id == 26).first():
        car26 = Car(
            id=26,
            name="Hyundai Tucson",
            plate_number="x",
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
        car26.plate_number = f"x{car26.id}"
        mock_cars_to_create.append(("Hyundai Tucson (id=26)", car26))
    else:
        print("ℹ️ Hyundai Tucson (id=26) уже существует")

    # Changan uni-k
    if not db.query(Car).filter(Car.id == 27).first():
        car27 = Car(
            id=27,
            name="Changan uni-k",
            plate_number="x",
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
        car27.plate_number = f"x{car27.id}"
        mock_cars_to_create.append(("Changan uni-k (id=27)", car27))
    else:
        print("ℹ️ Changan uni-k (id=27) уже существует")

    # ZEEKR 001 (второй)
    if not db.query(Car).filter(Car.id == 28).first():
        car28 = Car(
            id=28,
            name="ZEEKR 001",
            plate_number="x",
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
        car28.plate_number = f"x{car28.id}"
        mock_cars_to_create.append(("ZEEKR 001 второй (id=28)", car28))
    else:
        print("ℹ️ ZEEKR 001 второй (id=28) уже существует")

    # Toyota Land Cruiser 2018
    if not db.query(Car).filter(Car.id == 29).first():
        car29 = Car(
            id=29,
            name="Toyota Land Cruiser",
            plate_number="x",
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
        car29.plate_number = f"x{car29.id}"
        mock_cars_to_create.append(("Toyota Land Cruiser 2018 (id=29)", car29))
    else:
        print("ℹ️ Toyota Land Cruiser 2018 (id=29) уже существует")

    # BMW 540i 2024 
    if not db.query(Car).filter(Car.id == 30).first():
        car30 = Car(
            id=30,
            name="BMW 540i",
            plate_number="x",
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
        car30.plate_number = f"x{car30.id}"
        mock_cars_to_create.append(("BMW 540i 2024 (id=30)", car30))
    else:
        print("ℹ️ BMW 540i 2024 (id=30) уже существует")

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
