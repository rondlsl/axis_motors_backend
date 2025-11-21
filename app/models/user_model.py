from sqlalchemy import Column, Integer, String, DateTime, Enum, Numeric, Boolean, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
import enum
import uuid
from sqlalchemy.orm import relationship
from app.dependencies.database.database import Base
from app.utils.short_id import uuid_to_sid
from app.utils.time_utils import get_local_time


class UserRole(enum.Enum):
    ADMIN = "admin"
    USER = "user"
    REJECTED = "rejected"
    CLIENT = "client"
    PENDING = "pending"
    MECHANIC = "mechanic"
    GARANT = "GARANT"
    FINANCIER = "financier"
    MVD = "mvd"
    SUPPORT = "SUPPORT"                         # Служба поддержки
    PENDINGTOFIRST = "PENDINGTOFIRST"          # Загрузил документы, ждёт финансиста
    PENDINGTOSECOND = "PENDINGTOSECOND"        # Одобрен финансистом, ждёт МВД
    REJECTFIRSTDOC = "REJECTFIRSTDOC"          # Отказ финансиста: неверные документы
    REJECTFIRSTCERT = "REJECTFIRSTCERT"        # Отказ финансиста: отсутствуют сертификаты/справки для граждан Казахстана
    REJECTFIRST = "REJECTFIRST"                 # Отказ финансиста: финансовые причины
    REJECTSECOND = "REJECTSECOND"               # Отказ МВД: полный блок


class AutoClass(enum.Enum):
    A = "A"  # До 25 млн
    B = "B"  # До 40 млн  
    C = "C"  # 40+ млн


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    middle_name = Column(String(100), nullable=True)
    phone_number = Column(String, nullable=False, unique=False)
    email = Column(String, nullable=True)
    birth_date = Column(DateTime, nullable=True)
    iin = Column(String(12), nullable=True, unique=False)
    passport_number = Column(String(50), nullable=True)
    drivers_license_expiry = Column(DateTime, nullable=True)
    wallet_balance = Column(Numeric(10, 2), nullable=False, default=0)
    selfie_with_license_url = Column(String, nullable=True)
    selfie_url = Column(String, nullable=True)
    drivers_license_url = Column(String, nullable=True)
    id_card_front_url = Column(String, nullable=True)
    id_card_back_url = Column(String, nullable=True)
    id_card_expiry = Column(DateTime, nullable=True)
    psych_neurology_certificate_url = Column(String, nullable=True)
    narcology_certificate_url = Column(String, nullable=True)
    pension_contributions_certificate_url = Column(String, nullable=True)
    documents_verified = Column(Boolean, default=False, server_default="false")
    role = Column(Enum(UserRole), default=UserRole.CLIENT)
    last_sms_code = Column(String)
    sms_code_valid_until = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified_email = Column(Boolean, default=False, nullable=False, server_default="false")
    is_citizen_kz = Column(Boolean, default=False, nullable=False, server_default="false")  
    fcm_token = Column(String, nullable=True)
    locale = Column(String, nullable=False, server_default=text("'ru'"))
    auto_class = Column(ARRAY(String), nullable=True)  # Доступные классы авто (может быть несколько): A, B, C
    digital_signature = Column(String, nullable=True, unique=True)  # Уникальная электронная подпись пользователя
    is_consent_to_data_processing = Column(Boolean, default=False, nullable=False, server_default="false")  # Согласие на обработку персональных данных
    is_contract_read = Column(Boolean, default=False, nullable=False, server_default="false")  # Подтверждение прочтения договора
    is_user_agreement = Column(Boolean, default=False, nullable=False, server_default="false")  # Пользовательское соглашение
    
    # Дополнительные поля для админ-панели
    created_at = Column(DateTime, nullable=False, default=get_local_time)
    last_activity_at = Column(DateTime, nullable=True)
    upload_document_at = Column(DateTime, nullable=True) 
    admin_comment = Column(String, nullable=True)  # Комментарий админа/поддержки/механика

    rental_history = relationship("RentalHistory", back_populates="user",
                                  foreign_keys="[RentalHistory.user_id]")

    delivery_rentals = relationship("RentalHistory",
                                    foreign_keys="[RentalHistory.delivery_mechanic_id]",
                                    back_populates="delivery_mechanic")

    promos = relationship("UserPromoCode", back_populates="user")

    from app.models.car_model import Car
    owned_cars = relationship("Car", foreign_keys=[Car.owner_id], back_populates="owner")
    active_rental = relationship("Car", foreign_keys=[Car.current_renter_id],
                                 back_populates="current_renter", uselist=False)

    from app.models.notification_model import Notification

    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Notification.sent_at.desc()"
    )

    # Guarantor relationships
    sent_guarantor_requests = relationship("GuarantorRequest", foreign_keys="[GuarantorRequest.requestor_id]", back_populates="requestor")
    received_guarantor_requests = relationship("GuarantorRequest", foreign_keys="[GuarantorRequest.guarantor_id]", back_populates="guarantor")
    guaranteeing_for = relationship("Guarantor", foreign_keys="[Guarantor.guarantor_id]", back_populates="guarantor_user")
    guaranteed_by = relationship("Guarantor", foreign_keys="[Guarantor.client_id]", back_populates="client_user")
    
    # Application relationship
    application = relationship("Application", foreign_keys="[Application.user_id]", back_populates="user", uselist=False)
    
    # Связь для комментариев к автомобилям
    car_comments = relationship("CarComment", back_populates="author", cascade="all, delete-orphan")
    
    # Связь для подписанных договоров
    signed_contracts = relationship("UserContractSignature", back_populates="user", cascade="all, delete-orphan")
    
    # Связи для системы поддержки
    support_chats_as_client = relationship("SupportChat", foreign_keys="[SupportChat.azv_user_id]", back_populates="azv_user")
    support_chats_as_support = relationship("SupportChat", foreign_keys="[SupportChat.assigned_to]", back_populates="assigned_support")
    support_messages = relationship("SupportMessage", back_populates="sender_user")
    
    @property
    def sid(self) -> str:
        """Короткий ID для использования в API"""
        return uuid_to_sid(self.id)