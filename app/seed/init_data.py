"""
Модуль для инициализации тестовых данных
"""
import os
import uuid
from sqlalchemy.orm import Session
from app.models.car_model import Car, CarBodyType, CarAutoClass, CarStatus
from app.models.user_model import User, UserRole
from app.models.contract_model import ContractFile, ContractType


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
        
        # Создаем файлы договоров
        create_contract_files(db)
        
        print("Все тестовые данные успешно инициализированы")
        
    except Exception as e:
        print(f"Ошибка при инициализации тестовых данных: {e}")
        raise


def create_owner(db: Session) -> User:
    """Создает владельца автомобилей"""
    owner_phone = "71231111111"
    owner_iin = "980601523456" 
    owner = db.query(User).filter(User.phone_number == owner_phone).first()
    
    if not owner:
        owner = User(
            phone_number=owner_phone, 
            role=UserRole.CLIENT, 
            wallet_balance=0,
            iin=owner_iin,
            digital_signature=str(uuid.uuid4())
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        print("Владелец создан")
    else:
        print("Владелец уже существует")
        # Добавляем digital_signature если его нет
        if not owner.digital_signature:
            owner.digital_signature = str(uuid.uuid4())
            db.commit()
            print("Digital signature добавлена для владельца")
    
    return owner


def create_cars(db: Session, owner: User) -> None:
    """Создает автомобили (UUID id). Сопоставление по уникальному plate_number, без ручного задания id)."""
    specs = [
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
            "photos": get_car_photos("666AZV02"),
            "vin": "WDD2050461A123456",
            "color": "Серый",
        },
        {
            "name": "Hongqi e-qm5",
            "gps_id": "800283232",
            "gps_imei": "860803068139548",
            "engine_volume": 0.0,
            "year": 2025,
            "drive_type": 3,
            "price_per_minute": 60,
            "price_per_hour": 2500,
            "price_per_day": 40000,
            "plate_number": "890AVB09",
            "latitude": 43.25,
            "longitude": 76.95,
            "fuel_level": 100,
            "body_type": CarBodyType.ELECTRIC,
            "auto_class": CarAutoClass.A,
            "course": 0,
            "description": "Электромобиль в отличном состоянии.",
            "photos": get_car_photos("890AVB09"),
            "vin": "LFPHC7CD1S2B17968",
            "color": "Черный",
        },
        {
            "name": "Hyundai Tucson",
            "gps_id": "800339176",
            "gps_imei": "860803068146253",
            "engine_volume": 2.5,
            "year": 2022,
            "drive_type": 3,
            "transmission_type": "automatic",
            "price_per_minute": 75,
            "price_per_hour": 3500,
            "price_per_day": 55000,
            "plate_number": "959AWM02",
            "latitude": 43.225692,
            "longitude": 76.962056,
            "fuel_level": 27.55,
            "body_type": CarBodyType.CROSSOVER,
            "auto_class": CarAutoClass.A,
            "course": 4,
            "description": "Сильная царапина по левой стороне. От переднего бампера, по крылу до водительской двери. Треснуто левое боковое зеркало. Вмятина на нижней левой части багажника. Комплект автомобиля: шины Tourandor winter pro tss1 235/55 R19, 2 пары поликов (лето, сверху зима), запаска, домкрат.",
            "photos": get_car_photos("959AWM02"),
            "vin": "MXHJC81EDNK135885",
            "color": "Черный",
        },
        {
            "name": "Mercedes g63",
            "gps_id": "800298270",
            "gps_imei": "860803068155890",
            "engine_volume": 4.0,
            "year": 2021,
            "drive_type": 3,
            "transmission_type": "automatic",
            "price_per_minute": 490,
            "price_per_hour": 21875,
            "price_per_day": 350000,
            "plate_number": "888DON07",
            "latitude": 43.224048,
            "longitude": 76.961871,
            "fuel_level": 40,
            "course": 23,
            "body_type": CarBodyType.SUV,
            "auto_class": CarAutoClass.B,
            "description": "Легендарный внедорожник Mercedes G63.",
            "photos": get_car_photos("888DON07"),
            "vin": "W1NYC7GJXMX397708",
            "color": "Черный",
        },
        {
            "name": "BYD Han EV",
            "gps_id": "800370225",
            "gps_imei": "860803068155916",
            "engine_volume": 0.0,
            "year": 2025,
            "drive_type": 1, 
            "transmission_type": "automatic",
            "price_per_minute": 100,
            "price_per_hour": 4400,
            "price_per_day": 70000,
            "plate_number": "455BNI02",
            "latitude": 43.24,
            "longitude": 76.96,
            "fuel_level": 100,
            "body_type": CarBodyType.ELECTRIC,
            "auto_class": CarAutoClass.A,
            "course": 0,
            "description": "Все идеально. Комплект: мягкая щетка, буксировочный крюк, щипцы, насос.",
            "photos": get_car_photos("455BNI02"),
            "vin": "LC0CE6CD1S7066976",
            "color": "Черный",
        },
        {
            "name": "Maserati Ghibli",
            "gps_id": "800406786",
            "gps_imei": "860803068139613",
            "engine_volume": 3.0,
            "year": 2017,
            "drive_type": 2,  
            "transmission_type": "automatic",
            "price_per_minute": 195,
            "price_per_hour": 8800,
            "price_per_day": 140000,
            "plate_number": "195BGY02",
            "latitude": 43.224048,
            "longitude": 76.961871,
            "fuel_level": 50,
            "body_type": CarBodyType.SEDAN,
            "auto_class": CarAutoClass.B,
            "course": 0,
            "description": "1) Маленькая притертость на заднем бампере справа, около колеса 2) Нет парктроника на переднем бампере слева 3) Царапина на левой передней двери слева снизу от ручки двери. Комплект авто: 1) Кожаный паралон мазерати (черная палка) 2) Два парктроника 3) Домкрат 4) Буксировочный крюк 5) Белая воронка для бензина 6) Шестигранник 7) Отвертка (звездочка) 8) Красная отвертка с Головкой",
            "photos": get_car_photos("195BGY02"),
            "vin": "ZAM57YTA1J1287442",
            "color": "Черный",
        },
        {
            "name": "Toyota Camry",
            "gps_id": "800408106",
            "gps_imei": "860803068151071",
            "engine_volume": 2.5,
            "year": 2020,
            "drive_type": 1, 
            "transmission_type": "automatic",
            "price_per_minute": 70,
            "price_per_hour": 3200,
            "price_per_day": 50000,
            "plate_number": "357BLW02",
            "latitude": 43.224048,
            "longitude": 76.961871,
            "fuel_level": 50,
            "body_type": CarBodyType.SEDAN,
            "auto_class": CarAutoClass.A,
            "course": 0,
            "description": "Комплект автомобиля: 1) Запасное колесо 2) Красный пневмо домкрат 3) Шланг провода в пакете 4) Черный домкрат 5) Крюк для буксировки. Описание авто: 1) Царапина справа на заднем бампере 2) Царапина на заднем правом крыле и багажнике 3) Царапины на задней правой двери",
            "photos": get_car_photos("357BLW02"),
            "vin": "XW7BF3HK50S159916",
            "color": "Черный",
        },
        {
            "name": "Range Rover Sport Supercharged",
            "gps_id": "800409927",
            "gps_imei": "860803068151105",
            "engine_volume": 5.0,
            "year": 2015,
            "drive_type": 3, 
            "transmission_type": "automatic",
            "price_per_minute": 170,
            "price_per_hour": 7500,
            "price_per_day": 120000,
            "plate_number": "F980802",
            "latitude": 43.224048,
            "longitude": 76.961871,
            "fuel_level": 50,
            "body_type": CarBodyType.SUV,
            "auto_class": CarAutoClass.A,
            "course": 0,
            "description": "1) Скол и потертость на левом боковом зеркале 2) Потертость на правом боковом зеркале 3) Сколы на всех 4 дисках 4) Справа на багажнике и заднем бампере скол длиной в 5см 5) Скол на черном молдинге водительской двери. Комплект авто: 1) Запаска 2) Полный комплект домкрата 3) Аптечка 4) Крюк буксировки 5) Трос",
            "photos": get_car_photos("F980802"),
            "vin": "SALWA2EF5GA549626",
            "color": "Черный",
        },
    ]

    created = 0
    for spec in specs:
        plate = spec["plate_number"]
        existing = db.query(Car).filter(Car.plate_number == plate).first()
        if existing:
            print(f"{spec['name']} ({plate}) уже существует")
            continue
        car = Car(**spec, owner_id=owner.id)
        db.add(car)
        created += 1
        print(f"{spec['name']} ({plate}) добавлена")
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
            iin=mechanic_iin,
            digital_signature=str(uuid.uuid4())
        )
        db.add(mechanic)
        db.commit()
        db.refresh(mechanic)
        print("Механик создан")
    else:
        print("Механик уже существует")
        # Обновляем имена если они отсутствуют
        if not mechanic.first_name or not mechanic.last_name:
            mechanic.first_name = "Механик"
            mechanic.last_name = "Механик"
            db.commit()
            print("Имена механика обновлены")
        # Добавляем digital_signature если его нет
        if not mechanic.digital_signature:
            mechanic.digital_signature = str(uuid.uuid4())
            db.commit()
            print("Digital signature добавлена для механика")


def create_system_users(db: Session) -> None:
    """Создает системных пользователей (админ, финансист, МВД)"""
    
    # Админ
    admin_phone = "70000000000"
    admin_iin = "000000000000"  
    admin = db.query(User).filter(User.phone_number == admin_phone).first()
    if not admin:
        admin = User(
            phone_number=admin_phone,
            first_name="Admin",
            last_name="Admin",
            role=UserRole.ADMIN,
            documents_verified=True,
            is_active=True,
            iin=admin_iin,
            digital_signature=str(uuid.uuid4()),
            wallet_balance=0
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print("Админ создан")
    else:
        print("Админ уже существует")
        # Добавляем digital_signature если его нет
        if not admin.digital_signature:
            admin.digital_signature = str(uuid.uuid4())
            db.commit()
            print("Digital signature добавлена для админа")
    
    # Финансист
    financier_phone = "71234567899"
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
            digital_signature=str(uuid.uuid4())
        )
        db.add(financier)
        db.commit()
        db.refresh(financier)
        print("Финансист создан")
    else:
        print("Финансист уже существует")
        # Добавляем digital_signature если его нет
        if not financier.digital_signature:
            financier.digital_signature = str(uuid.uuid4())
            db.commit()
            print("Digital signature добавлена для финансиста")

    # МВД
    mvd_phone = "71234567898"
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
            digital_signature=str(uuid.uuid4())
        )
        db.add(mvd_user)
        db.commit()
        db.refresh(mvd_user)
        print("Пользователь МВД создан")
    else:
        print("Пользователь МВД уже существует")
        # Добавляем digital_signature если его нет
        if not mvd_user.digital_signature:
            mvd_user.digital_signature = str(uuid.uuid4())
            db.commit()
            print("Digital signature добавлена для пользователя МВД")


def create_mock_cars(db: Session, owner: User) -> None:
    """Создает моковые автомобили со статусом OCCUPIED"""
    
    mock_cars_to_create = []
    
    # Bentley Flying Spur
    if not db.query(Car).filter(Car.plate_number == "x4").first():
        car4 = Car(
            name="Bentley Flying Spur",
            plate_number="x4",
            latitude=49.8047,
            longitude=73.1094,
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
            description="Роскошный седан Bentley в отличном состоянии.",
            vin="1HGBH41JXMN109186",
            color="Черный"
        )
        car4.photos = get_car_photos("x4")
        mock_cars_to_create.append(("Bentley Flying Spur", car4))
    else:
        print("Bentley Flying Spur уже существует")

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
            description="Просторный внедорожник Hyundai для всей семьи.",
            vin="KM8J33CA2LU123456",
            color="Белый"
        )
        car5.photos = get_car_photos("x5")
        mock_cars_to_create.append(("Hyundai Palisade", car5))
    else:
        print("Hyundai Palisade уже существует")

    # Mercedes CLA 45s (второй)
    if not db.query(Car).filter(Car.plate_number == "x6").first():
        car6 = Car(
            name="Mercedes CLA 45s",
            plate_number="x6",
            latitude=45.0175,
            longitude=78.3739,
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
            description="Спортивный седан Mercedes с мощным двигателем.",
            vin="WDD2050461A654321",
            color="Красный"
        )
        car6.photos = get_car_photos("x6")
        mock_cars_to_create.append(("Mercedes CLA 45s", car6))
    else:
        print("Mercedes CLA 45s уже существует")

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
            description="Современный электромобиль ZEEKR с передовыми технологиями.",
            vin="LSGBF53E8EH789012",
            color="Синий"
        )
        car7.photos = get_car_photos("x7")
        mock_cars_to_create.append(("ZEEKR 001", car7))
    else:
        print("ZEEKR 001 уже существует")

    # Hongqi E-QM5 (второй)
    if not db.query(Car).filter(Car.plate_number == "x8").first():
        car8 = Car(
            name="Hongqi E-QM5",
            plate_number="x8",
            latitude=47.7844,
            longitude=67.7044,
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
            description="Новейший электромобиль Hongqi 2025 года.",
            vin="LSGBF53E8EH345678",
            color="Серый"
        )
        car8.photos = get_car_photos("x8")
        mock_cars_to_create.append(("Hongqi E-QM5", car8))
    else:
        print("Hongqi E-QM5 уже существует")

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
            description="Надежный внедорожник Toyota для любых дорог.",
            vin="JTEBU5JR2M5123456",
            color="Белый"
        )
        car9.photos = get_car_photos("x9")
        mock_cars_to_create.append(("Toyota Land Cruiser Prado", car9))
    else:
        print("Toyota Land Cruiser Prado уже существует")
    
    # Range Rover Sport
    if not db.query(Car).filter(Car.plate_number == "x10").first():
        car10 = Car(
            name="Range Rover Sport",
            plate_number="x10",
            latitude=43.3017,
            longitude=68.2517,
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
            description="Премиальный внедорожник Range Rover Sport.",
            vin="SALGS2SE6HA123456",
            color="Черный"
        )
        car10.photos = get_car_photos("x10")
        mock_cars_to_create.append(("Range Rover Sport", car10))
    else:
        print("Range Rover Sport уже существует")

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
            description="Спортивный седан Mercedes e63s.",
            vin="WDD2050461A987654",
            color="Серый"
        )
        car11.photos = get_car_photos("x11")
        mock_cars_to_create.append(("Mercedes e63s", car11))
    else:
        print("Mercedes e63s уже существует")

    # Toyota Camry 2020
    if not db.query(Car).filter(Car.plate_number == "x12").first():
        car12 = Car(
            name="Toyota Camry",
            plate_number="x12",
            latitude=50.4111,
            longitude=80.2275,
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
            description="Надежный седан Toyota Camry.",
            vin="JTNKARFU0L3123456",
            color="Серый"
        )
        car12.photos = get_car_photos("x12")
        mock_cars_to_create.append(("Toyota Camry 2020", car12))
    else:
        print("Toyota Camry 2020 уже существует")

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
            description="Спортивный седан BMW m5.",
            vin="WBSFV9C50LC123456",
            color="Черный"
        )
        car13.photos = get_car_photos("x13")
        mock_cars_to_create.append(("BMW m5", car13))
    else:
        print("BMW m5 уже существует")

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
            description="Просторный кроссовер Toyota Highlander.",
            vin="JTEBU5JR2M5234567",
            color="Белый"
        )
        car14.photos = get_car_photos("x14")
        mock_cars_to_create.append(("Toyota Highlander", car14))
    else:
        print("Toyota Highlander уже существует")

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
            description="Премиальный седан Lexus es 350.",
            vin="JTHBE1D25N5123456",
            color="Серый"
        )
        car15.photos = get_car_photos("x15")
        mock_cars_to_create.append(("Lexus es 350", car15))
    else:
        print("Lexus es 350 уже существует")

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
            description="Новейший седан Toyota Camry 2024.",
            vin="JTNKARFU0L4123456",
            color="Белый"
        )
        car16.photos = get_car_photos("x16")
        mock_cars_to_create.append(("Toyota Camry 2024", car16))
    else:
        print("Toyota Camry 2024 уже существует")

    # BMW 540i 2018
    if not db.query(Car).filter(Car.plate_number == "x17").first():
        car17 = Car(
            name="BMW 540i",
            plate_number="x17",
            latitude=51.2106,
            longitude=51.3679,
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
            description="Спортивный седан BMW 540i.",
            vin="WBAFR9C50LC123456",
            color="Серый"
        )
        car17.photos = get_car_photos("x17")
        mock_cars_to_create.append(("BMW 540i 2018", car17))
    else:
        print("BMW 540i 2018 уже существует")

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
            description="Гибридный кроссовер Lexus rx 350h.",
            vin="JTHBE1D25N5234567",
            color="Белый"
        )
        car18.photos = get_car_photos("x18")
        mock_cars_to_create.append(("Lexus rx 350h", car18))
    else:
        print("Lexus rx 350h уже существует")

    # Changan uni-v
    if not db.query(Car).filter(Car.plate_number == "x19").first():
        car19 = Car(
            name="Changan uni-v",
            plate_number="x19",
            latitude=51.7267,
            longitude=75.3222,
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
            description="Компактный седан Changan uni-v.",
            vin="LSGBF53E8EH567890",
            color="Красный"
        )
        car19.photos = get_car_photos("x19")
        mock_cars_to_create.append(("Changan uni-v", car19))
    else:
        print("Changan uni-v уже существует")

    # Lexus es 300h
    if not db.query(Car).filter(Car.plate_number == "x20").first():
        car20 = Car(
            name="Lexus es 300h",
            plate_number="x20",
            latitude=51.1605,
            longitude=71.4704,
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
            description="Гибридный седан Lexus es 300h.",
            vin="JTHBE1D25N5345678",
            color="Серый"
        )
        car20.photos = get_car_photos("x20")
        mock_cars_to_create.append(("Lexus es 300h", car20))
    else:
        print("Lexus es 300h уже существует")

    # Kia k8
    if not db.query(Car).filter(Car.plate_number == "x21").first():
        car21 = Car(
            name="Kia k8",
            plate_number="x21",
            latitude=50.2839,
            longitude=57.167,
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
            description="Премиальный седан Kia k8.",
            vin="KNDJT2A26N7123456",
            color="Черный"
        )
        car21.photos = get_car_photos("x21")
        mock_cars_to_create.append(("Kia k8", car21))
    else:
        print("Kia k8 уже существует")

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
            description="Новейший седан Toyota Camry 2024 (второй).",
            vin="JTNKARFU0L4223456",
            color="Серый"
        )
        car22.photos = get_car_photos("x22")
        mock_cars_to_create.append(("Toyota Camry 2024 второй", car22))
    else:
        print("Toyota Camry 2024 второй уже существует")

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
            description="Просторный внедорожник Hyundai Palisade.",
            vin="KM8J33CA2LU234567",
            color="Белый"
        )
        car23.photos = get_car_photos("x23")
        mock_cars_to_create.append(("Hyundai Palisade", car23))
    else:
        print("Hyundai Palisade уже существует")

    # Mercedes e200
    if not db.query(Car).filter(Car.plate_number == "x24").first():
        car24 = Car(
            name="Mercedes e200",
            plate_number="x24",
            latitude=42.9,
            longitude=71.3667,
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
            description="Элегантный седан Mercedes e200.",
            vin="WDD2050461A234567",
            color="Серый"
        )
        car24.photos = get_car_photos("x24")
        mock_cars_to_create.append(("Mercedes e200", car24))
    else:
        print("Mercedes e200 уже существует")

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
            description="Роскошный седан Mercedes s63.",
            vin="WDD2211741A345678",
            color="Черный"
        )
        car25.photos = get_car_photos("x25")
        mock_cars_to_create.append(("Mercedes s63", car25))
    else:
        print("Mercedes s63 уже существует")

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
            price_per_minute=90,
            price_per_hour=3800,
            price_per_day=60000,
            engine_volume=2.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный кроссовер Hyundai Tucson.",
            vin="KM8J33CA2LU345678",
            color="Белый"
        )
        car26.photos = get_car_photos("x26")
        mock_cars_to_create.append(("Hyundai Tucson", car26))
    else:
        print("Hyundai Tucson уже существует")

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
            description="Компактный кроссовер Changan uni-k.",
            vin="LSGBF53E8EH456789",
            color="Синий"
        )
        car27.photos = get_car_photos("x27")
        mock_cars_to_create.append(("Changan uni-k", car27))
    else:
        print("Changan uni-k уже существует")

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
            description="Современный электромобиль ZEEKR 001 (второй).",
            vin="LSGBF53E8EH567890",
            color="Белый"
        )
        car28.photos = get_car_photos("x28")
        mock_cars_to_create.append(("ZEEKR 001 второй", car28))
    else:
        print("ZEEKR 001 второй уже существует")

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
            description="Легендарный внедорожник Toyota Land Cruiser.",
            vin="JTEBU5JR2M5345678",
            color="Белый"
        )
        car29.photos = get_car_photos("x29")
        mock_cars_to_create.append(("Toyota Land Cruiser 2018", car29))
    else:
        print("Toyota Land Cruiser 2018 уже существует")

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
            description="Спортивный седан BMW 540i 2024.",
            vin="WBAFR9C50LC234567",
            color="Серый"
        )
        car30.photos = get_car_photos("x30")
        mock_cars_to_create.append(("BMW 540i 2024", car30))
    else:
        print("BMW 540i 2024 уже существует")

    # Mercedes G63
    if not db.query(Car).filter(Car.plate_number == "x31").first():
        car31 = Car(
            name="Mercedes G63",
            plate_number="x31",
            latitude=54.8753,
            longitude=69.162,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=45,
            price_per_minute=150,
            price_per_hour=7500,
            price_per_day=150000,
            engine_volume=4.0,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Легендарный внедорожник Mercedes G63 в отличном состоянии.",
            vin="WDC4632361A456789",
            color="Черный"
        )
        car31.photos = get_car_photos("x31")
        mock_cars_to_create.append(("Mercedes G63", car31))
    else:
        print("Mercedes G63 уже существует")

    # Toyota Camry 2021
    if not db.query(Car).filter(Car.plate_number == "x32").first():
        car32 = Car(
            name="Toyota Camry",
            plate_number="x32",
            latitude=43.540000,
            longitude=77.240000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=90,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.5,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный седан Toyota Camry 2021 года.",
            vin="JTNKARFU0L5123456",
            color="Серый"
        )
        car32.photos = get_car_photos("x32")
        mock_cars_to_create.append(("Toyota Camry 2021", car32))
    else:
        print("Toyota Camry 2021 уже существует")

    # Toyota Highlander 2020
    if not db.query(Car).filter(Car.plate_number == "x33").first():
        car33 = Car(
            name="Toyota Highlander",
            plate_number="x33",
            latitude=43.550000,
            longitude=77.250000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=135,
            price_per_minute=90,
            price_per_hour=4500,
            price_per_day=90000,
            engine_volume=2.5,
            year=2020,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный кроссовер Toyota Highlander для всей семьи.",
            vin="JTEBU5JR2M5445678",
            color="Белый"
        )
        car33.photos = get_car_photos("x33")
        mock_cars_to_create.append(("Toyota Highlander 2020", car33))
    else:
        print("Toyota Highlander 2020 уже существует")

    # Mercedes E-Class 2024
    if not db.query(Car).filter(Car.plate_number == "x34").first():
        car34 = Car(
            name="Mercedes E-Class",
            plate_number="x34",
            latitude=43.560000,
            longitude=77.260000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=180,
            price_per_minute=100,
            price_per_hour=5000,
            price_per_day=100000,
            engine_volume=2.0,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Mercedes E-Class 2024 года.",
            vin="WDD2130641A567890",
            color="Серый"
        )
        car34.photos = get_car_photos("x34")
        mock_cars_to_create.append(("Mercedes E-Class 2024", car34))
    else:
        print("Mercedes E-Class 2024 уже существует")

    # Toyota Land Cruiser 2019
    if not db.query(Car).filter(Car.plate_number == "x35").first():
        car35 = Car(
            name="Toyota Land Cruiser",
            plate_number="x35",
            latitude=52.9631,
            longitude=63.1192,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=225,
            price_per_minute=120,
            price_per_hour=6000,
            price_per_day=120000,
            engine_volume=4.6,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Легендарный внедорожник Toyota Land Cruiser для любых условий.",
            vin="JTEBU5JR2M5556789",
            color="Белый"
        )
        car35.photos = get_car_photos("x35")
        mock_cars_to_create.append(("Toyota Land Cruiser 2019", car35))
    else:
        print("Toyota Land Cruiser 2019 уже существует")

    # Lexus GX 550 2024
    if not db.query(Car).filter(Car.plate_number == "x36").first():
        car36 = Car(
            name="Lexus GX 550",
            plate_number="x36",
            latitude=43.580000,
            longitude=77.280000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=130,
            price_per_hour=6500,
            price_per_day=130000,
            engine_volume=3.4,
            year=2024,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный внедорожник Lexus GX 550 последнего поколения.",
            vin="JTHBE1D25N5567890",
            color="Черный"
        )
        car36.photos = get_car_photos("x36")
        mock_cars_to_create.append(("Lexus GX 550 2024", car36))
    else:
        print("Lexus GX 550 2024 уже существует")

    # Toyota Land Cruiser 2022
    if not db.query(Car).filter(Car.plate_number == "x37").first():
        car37 = Car(
            name="Toyota Land Cruiser",
            plate_number="x37",
            latitude=43.590000,
            longitude=77.290000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=315,
            price_per_minute=125,
            price_per_hour=6250,
            price_per_day=125000,
            engine_volume=3.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный внедорожник Toyota Land Cruiser 2022 года.",
            vin="JTEBU5JR2M5678901",
            color="Белый"
        )
        car37.photos = get_car_photos("x37")
        mock_cars_to_create.append(("Toyota Land Cruiser 2022", car37))
    else:
        print("Toyota Land Cruiser 2022 уже существует")

    # Kia K8 2025
    if not db.query(Car).filter(Car.plate_number == "x38").first():
        car38 = Car(
            name="Kia K8",
            plate_number="x38",
            latitude=53.2844,
            longitude=69.3918,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=0,
            price_per_minute=85,
            price_per_hour=4250,
            price_per_day=85000,
            engine_volume=2.5,
            year=2025,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Kia K8 новейшего поколения.",
            vin="KNDJT2A26N8234567",
            color="Черный"
        )
        car38.photos = get_car_photos("x38")
        mock_cars_to_create.append(("Kia K8 2025", car38))
    else:
        print("Kia K8 2025 уже существует")

    # Porsche Taycan Turbo 2022
    if not db.query(Car).filter(Car.plate_number == "x39").first():
        car39 = Car(
            name="Porsche Taycan Turbo",
            plate_number="x39",
            latitude=43.610000,
            longitude=77.310000,
            gps_id=None,
            gps_imei=None,
            fuel_level=100,
            course=45,
            price_per_minute=180,
            price_per_hour=9000,
            price_per_day=180000,
            engine_volume=0.0,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.ELECTRIC,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный электромобиль Porsche Taycan Turbo.",
            vin="WP0ZZZY1NNS456789",
            color="Серый"
        )
        car39.photos = get_car_photos("x39")
        mock_cars_to_create.append(("Porsche Taycan Turbo 2022", car39))
    else:
        print("Porsche Taycan Turbo 2022 уже существует")

    # Hyundai Sonata N-Line 2021
    if not db.query(Car).filter(Car.plate_number == "x40").first():
        car40 = Car(
            name="Hyundai Sonata N-Line",
            plate_number="x40",
            latitude=52.2873,
            longitude=76.9674,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=90,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=2.5,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивная версия седана Hyundai Sonata N-Line.",
            vin="KM8J33CA2LU456789",
            color="Красный"
        )
        car40.photos = get_car_photos("x40")
        mock_cars_to_create.append(("Hyundai Sonata N-Line 2021", car40))
    else:
        print("Hyundai Sonata N-Line 2021 уже существует")

    # Mercedes S 500 2013
    if not db.query(Car).filter(Car.plate_number == "x41").first():
        car41 = Car(
            name="Mercedes S 500",
            plate_number="x41",
            latitude=50.0547,
            longitude=72.9642,
            gps_id=None,
            gps_imei=None,
            fuel_level=65,
            course=135,
            price_per_minute=120,
            price_per_hour=6000,
            price_per_day=120000,
            engine_volume=4.7,
            year=2013,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Роскошный седан Mercedes S 500 в отличном состоянии.",
            vin="WDD2211741A456789",
            color="Черный"
        )
        car41.photos = get_car_photos("x41")
        mock_cars_to_create.append(("Mercedes S 500 2013", car41))
    else:
        print("Mercedes S 500 2013 уже существует")

    # Toyota Camry 2018
    if not db.query(Car).filter(Car.plate_number == "x42").first():
        car42 = Car(
            name="Toyota Camry",
            plate_number="x42",
            latitude=43.640000,
            longitude=77.340000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=180,
            price_per_minute=65,
            price_per_hour=3250,
            price_per_day=65000,
            engine_volume=2.5,
            year=2018,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный седан Toyota Camry 2018 года.",
            vin="JTNKARFU0L6123456",
            color="Серый"
        )
        car42.photos = get_car_photos("x42")
        mock_cars_to_create.append(("Toyota Camry 2018", car42))
    else:
        print("Toyota Camry 2018 уже существует")

    # Lexus LX570 2019
    if not db.query(Car).filter(Car.plate_number == "x43").first():
        car43 = Car(
            name="Lexus LX570",
            plate_number="x43",
            latitude=43.650000,
            longitude=77.350000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=225,
            price_per_minute=140,
            price_per_hour=7000,
            price_per_day=140000,
            engine_volume=5.7,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный внедорожник Lexus LX570 для комфортных поездок.",
            vin="JTHBE1D25N5678901",
            color="Черный"
        )
        car43.photos = get_car_photos("x43")
        mock_cars_to_create.append(("Lexus LX570 2019", car43))
    else:
        print("Lexus LX570 2019 уже существует")

    # BMW M5 2022
    if not db.query(Car).filter(Car.plate_number == "x44").first():
        car44 = Car(
            name="BMW M5",
            plate_number="x44",
            latitude=43.660000,
            longitude=77.360000,
            gps_id=None,
            gps_imei=None,
            fuel_level=65,
            course=270,
            price_per_minute=150,
            price_per_hour=7500,
            price_per_day=150000,
            engine_volume=4.4,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан BMW M5 с мощным двигателем.",
            vin="WBSFV9C50LC456789",
            color="Черный"
        )
        car44.photos = get_car_photos("x44")
        mock_cars_to_create.append(("BMW M5 2022", car44))
    else:
        print("BMW M5 2022 уже существует")

    # BMW 530i 2025
    if not db.query(Car).filter(Car.plate_number == "x45").first():
        car45 = Car(
            name="BMW 530i",
            plate_number="x45",
            latitude=44.8488,
            longitude=65.5092,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=315,
            price_per_minute=110,
            price_per_hour=5500,
            price_per_day=110000,
            engine_volume=2.0,
            year=2025,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Новейший седан BMW 530i 2025 года.",
            vin="WBAFR9C50LC567890",
            color="Серый"
        )
        car45.photos = get_car_photos("x45")
        mock_cars_to_create.append(("BMW 530i 2025", car45))
    else:
        print("BMW 530i 2025 уже существует")

    # Hyundai Sonata 2024
    if not db.query(Car).filter(Car.plate_number == "x46").first():
        car46 = Car(
            name="Hyundai Sonata",
            plate_number="x46",
            latitude=43.680000,
            longitude=77.380000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=0,
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
            description="Современный седан Hyundai Sonata 2024 года.",
            vin="KM8J33CA2LU567890",
            color="Белый"
        )
        car46.photos = get_car_photos("x46")
        mock_cars_to_create.append(("Hyundai Sonata 2024", car46))
    else:
        print("Hyundai Sonata 2024 уже существует")

    # Kia K5 2021
    if not db.query(Car).filter(Car.plate_number == "x47").first():
        car47 = Car(
            name="Kia K5",
            plate_number="x47",
            latitude=43.690000,
            longitude=77.390000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=45,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.0,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан Kia K5 с современным дизайном.",
            vin="KNDJT2A26N9345678",
            color="Красный"
        )
        car47.photos = get_car_photos("x47")
        mock_cars_to_create.append(("Kia K5 2021", car47))
    else:
        print("Kia K5 2021 уже существует")

    # Kia K8 2021
    if not db.query(Car).filter(Car.plate_number == "x48").first():
        car48 = Car(
            name="Kia K8",
            plate_number="x48",
            latitude=43.700000,
            longitude=77.400000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=90,
            price_per_minute=85,
            price_per_hour=4250,
            price_per_day=85000,
            engine_volume=2.5,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Kia K8 2021 года.",
            vin="KNDJT2A26N9456789",
            color="Черный"
        )
        car48.photos = get_car_photos("x48")
        mock_cars_to_create.append(("Kia K8 2021", car48))
    else:
        print("Kia K8 2021 уже существует")

    # Kia K8 2022
    if not db.query(Car).filter(Car.plate_number == "x49").first():
        car49 = Car(
            name="Kia K8",
            plate_number="x49",
            latitude=43.710000,
            longitude=77.410000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=135,
            price_per_minute=85,
            price_per_hour=4250,
            price_per_day=85000,
            engine_volume=2.5,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный седан Kia K8 2022 года.",
            vin="KNDJT2A26N9567890",
            color="Серый"
        )
        car49.photos = get_car_photos("x49")
        mock_cars_to_create.append(("Kia K8 2022", car49))
    else:
        print("Kia K8 2022 уже существует")

    # BMW X6M 2016
    if not db.query(Car).filter(Car.plate_number == "x50").first():
        car50 = Car(
            name="BMW X6M",
            plate_number="x50",
            latitude=43.720000,
            longitude=77.420000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=180,
            price_per_minute=140,
            price_per_hour=7000,
            price_per_day=140000,
            engine_volume=4.4,
            year=2016,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный кроссовер BMW X6M с мощным двигателем.",
            vin="WBAFR9C50LC678901",
            color="Черный"
        )
        car50.photos = get_car_photos("x50")
        mock_cars_to_create.append(("BMW X6M 2016", car50))
    else:
        print("BMW X6M 2016 уже существует")

    # Toyota Camry 2021 (третий)
    if not db.query(Car).filter(Car.plate_number == "x51").first():
        car51 = Car(
            name="Toyota Camry",
            plate_number="x51",
            latitude=43.730000,
            longitude=77.430000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=225,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.5,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный седан Toyota Camry 2021 года.",
            vin="JTNKARFU0L7234567",
            color="Белый"
        )
        car51.photos = get_car_photos("x51")
        mock_cars_to_create.append(("Toyota Camry 2021 третий", car51))
    else:
        print("Toyota Camry 2021 третий уже существует")

    # BMW 530d 2022
    if not db.query(Car).filter(Car.plate_number == "x52").first():
        car52 = Car(
            name="BMW 530d",
            plate_number="x52",
            latitude=47.0945,
            longitude=51.9238,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=105,
            price_per_hour=5250,
            price_per_day=105000,
            engine_volume=2.0,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Дизельный седан BMW 530d с экономичным двигателем.",
            vin="WBAFR9C50LC789012",
            color="Серый"
        )
        car52.photos = get_car_photos("x52")
        mock_cars_to_create.append(("BMW 530d 2022", car52))
    else:
        print("BMW 530d 2022 уже существует")

    # Toyota Land Cruiser 2016
    if not db.query(Car).filter(Car.plate_number == "x53").first():
        car53 = Car(
            name="Toyota Land Cruiser",
            plate_number="x53",
            latitude=43.750000,
            longitude=77.450000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=315,
            price_per_minute=110,
            price_per_hour=5500,
            price_per_day=110000,
            engine_volume=4.0,
            year=2016,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Надежный внедорожник Toyota Land Cruiser 2016 года.",
            vin="JTEBU5JR2M5789012",
            color="Белый"
        )
        car53.photos = get_car_photos("x53")
        mock_cars_to_create.append(("Toyota Land Cruiser 2016", car53))
    else:
        print("Toyota Land Cruiser 2016 уже существует")

    # Kia K5 2020
    if not db.query(Car).filter(Car.plate_number == "x54").first():
        car54 = Car(
            name="Kia K5",
            plate_number="x54",
            latitude=42.3154,
            longitude=69.5867,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=0,
            price_per_minute=65,
            price_per_hour=3250,
            price_per_day=65000,
            engine_volume=1.6,
            year=2020,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Компактный седан Kia K5 с экономичным двигателем.",
            vin="KNDJT2A26N9678901",
            color="Серый"
        )
        car54.photos = get_car_photos("x54")
        mock_cars_to_create.append(("Kia K5 2020", car54))
    else:
        print("Kia K5 2020 уже существует")

    # Hyundai Palisade 2023
    if not db.query(Car).filter(Car.plate_number == "x55").first():
        car55 = Car(
            name="Hyundai Palisade",
            plate_number="x55",
            latitude=43.655,
            longitude=51.1588,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=45,
            price_per_minute=95,
            price_per_hour=4750,
            price_per_day=95000,
            engine_volume=3.8,
            year=2023,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный внедорожник Hyundai Palisade для комфортных поездок.",
            vin="KM8J33CA2LU678901",
            color="Белый"
        )
        car55.photos = get_car_photos("x55")
        mock_cars_to_create.append(("Hyundai Palisade 2023", car55))
    else:
        print("Hyundai Palisade 2023 уже существует")

    # Kia Sportage 2022
    if not db.query(Car).filter(Car.plate_number == "x56").first():
        car56 = Car(
            name="Kia Sportage",
            plate_number="x56",
            latitude=43.780000,
            longitude=77.480000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=90,
            price_per_minute=75,
            price_per_hour=3750,
            price_per_day=75000,
            engine_volume=2.0,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Современный кроссовер Kia Sportage с стильным дизайном.",
            vin="KNDJT2A26N9789012",
            color="Белый"
        )
        car56.photos = get_car_photos("x56")
        mock_cars_to_create.append(("Kia Sportage 2022", car56))
    else:
        print("Kia Sportage 2022 уже существует")

    # Lexus RX350 2019
    if not db.query(Car).filter(Car.plate_number == "x57").first():
        car57 = Car(
            name="Lexus RX350",
            plate_number="x57",
            latitude=43.790000,
            longitude=77.490000,
            gps_id=None,
            gps_imei=None,
            fuel_level=80,
            course=135,
            price_per_minute=100,
            price_per_hour=5000,
            price_per_day=100000,
            engine_volume=3.5,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный кроссовер Lexus RX350 для комфорта и надежности.",
            vin="JTHBE1D25N5789012",
            color="Белый"
        )
        car57.photos = get_car_photos("x57")
        mock_cars_to_create.append(("Lexus RX350 2019", car57))
    else:
        print("Lexus RX350 2019 уже существует")

    # BMW X5 2022
    if not db.query(Car).filter(Car.plate_number == "x58").first():
        car58 = Car(
            name="BMW X5",
            plate_number="x58",
            latitude=43.800000,
            longitude=77.500000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=180,
            price_per_minute=120,
            price_per_hour=6000,
            price_per_day=120000,
            engine_volume=3.0,
            year=2022,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный кроссовер BMW X5 с отличными ходовыми качествами.",
            vin="WBAFR9C50LC890123",
            color="Черный"
        )
        car58.photos = get_car_photos("x58")
        mock_cars_to_create.append(("BMW X5 2022", car58))
    else:
        print("BMW X5 2022 уже существует")

    # BMW X5 2021
    if not db.query(Car).filter(Car.plate_number == "x59").first():
        car59 = Car(
            name="BMW X5",
            plate_number="x59",
            latitude=43.810000,
            longitude=77.510000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=225,
            price_per_minute=115,
            price_per_hour=5750,
            price_per_day=115000,
            engine_volume=3.0,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный кроссовер BMW X5 2021 года.",
            vin="WBAFR9C50LC901234",
            color="Серый"
        )
        car59.photos = get_car_photos("x59")
        mock_cars_to_create.append(("BMW X5 2021", car59))
    else:
        print("BMW X5 2021 уже существует")

    # Toyota RAV4 2020
    if not db.query(Car).filter(Car.plate_number == "x60").first():
        car60 = Car(
            name="Toyota RAV4",
            plate_number="x60",
            latitude=43.820000,
            longitude=77.520000,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=270,
            price_per_minute=70,
            price_per_hour=3500,
            price_per_day=70000,
            engine_volume=2.0,
            year=2020,
            drive_type=3,
            body_type=CarBodyType.CROSSOVER,
            auto_class=CarAutoClass.A,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Популярный кроссовер Toyota RAV4 для городских поездок.",
            vin="JTEBU5JR2M5890123",
            color="Белый"
        )
        car60.photos = get_car_photos("x60")
        mock_cars_to_create.append(("Toyota RAV4 2020", car60))
    else:
        print("Toyota RAV4 2020 уже существует")

    # Range Rover 2019
    if not db.query(Car).filter(Car.plate_number == "x61").first():
        car61 = Car(
            name="Range Rover",
            plate_number="x61",
            latitude=43.830000,
            longitude=77.530000,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=315,
            price_per_minute=130,
            price_per_hour=6500,
            price_per_day=130000,
            engine_volume=5.0,
            year=2019,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Премиальный внедорожник Range Rover для роскошных поездок.",
            vin="SALGS2SE6HA456789",
            color="Черный"
        )
        car61.photos = get_car_photos("x61")
        mock_cars_to_create.append(("Range Rover 2019", car61))
    else:
        print("Range Rover 2019 уже существует")

    # BMW X7 2021
    if not db.query(Car).filter(Car.plate_number == "x62").first():
        car62 = Car(
            name="BMW X7",
            plate_number="x62",
            latitude=53.2198,
            longitude=63.6354,
            gps_id=None,
            gps_imei=None,
            fuel_level=75,
            course=0,
            price_per_minute=135,
            price_per_hour=6750,
            price_per_day=135000,
            engine_volume=3.0,
            year=2021,
            drive_type=3,
            body_type=CarBodyType.SUV,
            auto_class=CarAutoClass.C,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Просторный внедорожник BMW X7 для всей семьи.",
            vin="WBAFR9C50LC012345",
            color="Белый"
        )
        car62.photos = get_car_photos("x62")
        mock_cars_to_create.append(("BMW X7 2021", car62))
    else:
        print("BMW X7 2021 уже существует")

    # BMW 530 2018
    if not db.query(Car).filter(Car.plate_number == "x63").first():
        car63 = Car(
            name="BMW 530",
            plate_number="x63",
            latitude=49.9481,
            longitude=82.6278,
            gps_id=None,
            gps_imei=None,
            fuel_level=70,
            course=45,
            price_per_minute=95,
            price_per_hour=4750,
            price_per_day=95000,
            engine_volume=2.0,
            year=2018,
            drive_type=3,
            body_type=CarBodyType.SEDAN,
            auto_class=CarAutoClass.B,
            owner_id=owner.id,
            status=CarStatus.OCCUPIED,
            description="Спортивный седан BMW 530 2018 года.",
            vin="WBAFR9C50LC123456",
            color="Серый"
        )
        car63.photos = get_car_photos("x63")
        mock_cars_to_create.append(("BMW 530 2018", car63))
    else:
        print("BMW 530 2018 уже существует")

    # Добавляем все моковые автомобили одним commit'ом
    if mock_cars_to_create:
        for name, car in mock_cars_to_create:
            db.add(car)
            print(f"{name} добавлен (моковый)")
        db.commit()


def get_car_photos(plate_number: str) -> list[str]:
    """Получает список фотографий автомобиля из папки uploads/cars/{plate_number}"""
    if plate_number.startswith("x") and plate_number[1:].isdigit():
        folder_name = plate_number.upper()  
    else:
        folder_name = plate_number
    
    photos_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "cars", folder_name)
    photos = []
    
    if os.path.isdir(photos_dir):
        for fname in sorted(os.listdir(photos_dir)):
            if os.path.isfile(os.path.join(photos_dir, fname)):
                photos.append(f"/uploads/cars/{folder_name}/{fname}")
    
    return photos


def create_contract_files(db: Session) -> None:
    """Создает файлы договоров в базе данных"""
    
    contracts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "contracts")
    os.makedirs(contracts_dir, exist_ok=True)
    
    contract_files = {
        ContractType.CONSENT_TO_DATA_PROCESSING: "consent_to_data_processing.docx",
        ContractType.USER_AGREEMENT: "user_agreement.docx", 
        ContractType.MAIN_CONTRACT: "main_contract.docx",
        ContractType.RENTAL_MAIN_CONTRACT: "rental_main_contract.docx",
        ContractType.GUARANTOR_CONTRACT: "guarantor_contract.docx",
        ContractType.GUARANTOR_MAIN_CONTRACT: "guarantor_main_contract.docx",
        ContractType.APPENDIX_7_1: "appendix_7_1.docx",
        ContractType.APPENDIX_7_2: "appendix_7_2.docx"
    }
    
    for contract_type, filename in contract_files.items():
        existing_file = db.query(ContractFile).filter(
            ContractFile.contract_type == contract_type,
            ContractFile.is_active == True
        ).first()
        
        if existing_file:
            print(f"Файл договора {contract_type.value} уже существует")
            continue
            
        file_uuid = str(uuid.uuid4())
        file_extension = os.path.splitext(filename)[1]
        unique_filename = f"{os.path.splitext(filename)[0]}_{file_uuid}{file_extension}"
        file_path = f"uploads/contracts/{unique_filename}"
        
        full_file_path = os.path.join(os.path.dirname(__file__), "..", "..", file_path)
        with open(full_file_path, 'w', encoding='utf-8') as f:
            f.write(f"Шаблон договора для типа: {contract_type.value}")
        
        contract_file = ContractFile(
            contract_type=contract_type,
            file_path=file_path,
            file_name=unique_filename,
            is_active=True
        )
        
        db.add(contract_file)
        print(f"Создан файл договора: {contract_type.value}")
    
    db.commit()
    print("Все файлы договоров успешно созданы")
