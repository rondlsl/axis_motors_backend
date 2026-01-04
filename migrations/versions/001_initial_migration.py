"""Initial migration with all models

Revision ID: 001_initial_migration
Revises: 
Create Date: 2025-10-20 06:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '001_initial_migration'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create all enum types first
    create_enums()
    
    # Create all tables
    create_users_table()
    create_user_devices_table()
    create_tokens_table()
    create_cars_table()
    create_applications_table()
    create_guarantor_requests_table()
    create_guarantors_table()
    create_rental_history_table()
    create_rental_reviews_table()
    create_rental_actions_table()
    create_car_comments_table()
    create_verification_codes_table()
    create_contract_files_table()
    create_user_contract_signatures_table()
    create_notifications_table()
    create_promo_codes_table()
    create_user_promo_codes_table()
    create_support_actions_table()
    create_wallet_transactions_table()
    create_support_chats_table()
    create_support_messages_table()
    create_app_versions_table()
    create_car_availability_history_table()


def create_enums():
    """Create all enum types"""
    
    # UserRole enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE userrole AS ENUM (
                'admin', 'user', 'rejected', 'client', 'pending', 'mechanic', 'garant', 
                'financier', 'mvd', 'support', 'driver', 'pendingtofirst', 'pendingtosecond', 
                'rejectfirstdoc', 'rejectfirstcert', 'rejectfirst', 'rejectsecond',
                'ADMIN', 'USER', 'REJECTED', 'CLIENT', 'PENDING', 'MECHANIC', 'GARANT',
                'FINANCIER', 'MVD', 'SUPPORT', 'DRIVER', 'PENDINGTOFIRST', 'PENDINGTOSECOND', 
                'REJECTFIRSTDOC', 'REJECTFIRSTCERT', 'REJECTFIRST', 'REJECTSECOND'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # AutoClass enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE autoclass AS ENUM ('A', 'B', 'C');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # CarBodyType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE carbodytype AS ENUM (
                'SEDAN', 'SUV', 'CROSSOVER', 'COUPE', 'HATCHBACK', 'CONVERTIBLE', 
                'WAGON', 'MINIBUS', 'ELECTRIC',
                'sedan', 'suv', 'crossover', 'coupe', 'hatchback', 'convertible', 
                'wagon', 'minibus', 'electric'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # CarAutoClass enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE carautoclass AS ENUM ('A', 'B', 'C');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # TransmissionType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE transmissiontype AS ENUM (
                'manual', 'automatic', 'cvt', 'semi_automatic',
                'MANUAL', 'AUTOMATIC', 'CVT', 'SEMI_AUTOMATIC'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # CarStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE carstatus AS ENUM (
                'FREE', 'PENDING', 'IN_USE', 'DELIVERING', 'SERVICE', 
                'RESERVED', 'SCHEDULED', 'OWNER', 'OCCUPIED',
                'free', 'pending', 'in_use', 'delivering', 'service', 
                'reserved', 'scheduled', 'owner', 'occupied'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # ApplicationStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE applicationstatus AS ENUM (
                'pending', 'approved', 'rejected',
                'PENDING', 'APPROVED', 'REJECTED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # GuarantorRequestStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE guarantorrequeststatus AS ENUM (
                'pending', 'accepted', 'rejected', 'expired',
                'PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # VerificationStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE verificationstatus AS ENUM (
                'not_verified', 'verified', 'rejected',
                'NOT_VERIFIED', 'VERIFIED', 'REJECTED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # RentalType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE rentaltype AS ENUM (
                'minutes', 'hours', 'days',
                'MINUTES', 'HOURS', 'DAYS'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # RentalStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE rentalstatus AS ENUM (
                'reserved', 'in_use', 'completed', 'delivering', 'delivering_in_progress',
                'delivery_reserved', 'cancelled', 'scheduled', 'RESERVED', 'IN_USE', 
                'COMPLETED', 'DELIVERING', 'DELIVERING_IN_PROGRESS', 'DELIVERY_RESERVED', 
                'CANCELLED', 'SCHEDULED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # ActionType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE actiontype AS ENUM (
                'open_vehicle', 'close_vehicle', 'give_key', 'take_key', 
                'lock_engine', 'unlock_engine',
                'OPEN_VEHICLE', 'CLOSE_VEHICLE', 'GIVE_KEY', 'TAKE_KEY', 
                'LOCK_ENGINE', 'UNLOCK_ENGINE'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # ContractType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE contracttype AS ENUM (
                'guarantor_contract', 'guarantor_main_contract', 'user_agreement',
                'consent_to_data_processing', 'main_contract', 'rental_main_contract',
                'appendix_7_1', 'appendix_7_2',
                'GUARANTOR_CONTRACT', 'GUARANTOR_MAIN_CONTRACT', 'USER_AGREEMENT',
                'CONSENT_TO_DATA_PROCESSING', 'MAIN_CONTRACT', 'RENTAL_MAIN_CONTRACT',
                'APPENDIX_7_1', 'APPENDIX_7_2'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # NotificationStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE notificationstatus AS ENUM (
                'mechanic_assigned', 'car_delivered', 'delivery_new_order', 'delivery_started',
                'new_car_for_inspection', 'paid_waiting_soon', 'paid_waiting_started',
                'low_balance', 'basic_tariff_ending_soon', 'out_of_tariff_charges',
                'delivery_cancelled', 'balance_exhausted', 'delivery_delay_penalty',
                'documents_recheck_required',
                'application_rejected_financier', 'application_rejected_mvd',
                'application_approved_financier', 'application_approved_mvd',
                'guarantor_invitation', 'guarantor_accepted',
                'fuel_empty', 'account_balance_low', 'zone_exit', 'rpm_spikes',
                'verification_passed', 'verification_failed', 'promo_code_available',
                'guarantor_connected', 'fuel_refill_detected', 'courier_found',
                'courier_delivered', 'fine_issued', 'balance_top_up',
                'basic_tariff_ending', 'locks_open', 'impact_weak', 'impact_medium',
                'impact_strong', 'birthday', 'friday_evening', 'monday_morning',
                'new_car_available', 'car_nearby', 'holiday_greeting', 'airport_location',
                'car_viewed_exit', 'documents_uploaded', 'email_verification_required', 'missing_documents_bonus',
                'rental_extended',
                'MECHANIC_ASSIGNED', 'CAR_DELIVERED', 'DELIVERY_NEW_ORDER', 'DELIVERY_STARTED',
                'NEW_CAR_FOR_INSPECTION', 'PAID_WAITING_SOON', 'PAID_WAITING_STARTED',
                'LOW_BALANCE', 'BASIC_TARIFF_ENDING_SOON', 'OUT_OF_TARIFF_CHARGES',
                'DELIVERY_CANCELLED', 'BALANCE_EXHAUSTED', 'DELIVERY_DELAY_PENALTY',
                'DOCUMENTS_RECHECK_REQUIRED',
                'APPLICATION_REJECTED_FINANCIER', 'APPLICATION_REJECTED_MVD',
                'APPLICATION_APPROVED_FINANCIER', 'APPLICATION_APPROVED_MVD',
                'GUARANTOR_INVITATION', 'GUARANTOR_ACCEPTED',
                'FUEL_EMPTY', 'ACCOUNT_BALANCE_LOW', 'ZONE_EXIT', 'RPM_SPIKES',
                'VERIFICATION_PASSED', 'VERIFICATION_FAILED', 'PROMO_CODE_AVAILABLE',
                'GUARANTOR_CONNECTED', 'FUEL_REFILL_DETECTED', 'COURIER_FOUND',
                'COURIER_DELIVERED', 'FINE_ISSUED', 'BALANCE_TOP_UP',
                'BASIC_TARIFF_ENDING', 'LOCKS_OPEN', 'IMPACT_WEAK', 'IMPACT_MEDIUM',
                'IMPACT_STRONG', 'BIRTHDAY', 'FRIDAY_EVENING', 'MONDAY_MORNING',
                'NEW_CAR_AVAILABLE', 'CAR_NEARBY', 'HOLIDAY_GREETING', 'AIRPORT_LOCATION',
                'CAR_VIEWED_EXIT', 'DOCUMENTS_UPLOADED', 'EMAIL_VERIFICATION_REQUIRED', 'MISSING_DOCUMENTS_BONUS',
                'RENTAL_EXTENDED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # UserPromoStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE userpromostatus AS ENUM (
                'activated', 'used',
                'ACTIVATED', 'USED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # WalletTransactionType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE wallettransactiontype AS ENUM (
                'deposit', 'promo_bonus', 'company_bonus', 'refund', 'rent_open_fee', 'rent_waiting_fee',
                'rent_minute_charge', 'rent_overtime_fee', 'rent_distance_fee',
                'rent_base_charge', 'rent_fuel_fee', 'delivery_fee', 'delivery_penalty',
                'manual_adjustment', 'admin_deduction', 'damage_penalty', 'fine_penalty', 'owner_waiting_fee_share', 'sanction_penalty',
                'reservation_rebooking_fee', 'rent_driver_fee',
                'DEPOSIT', 'PROMO_BONUS', 'COMPANY_BONUS', 'REFUND', 'RENT_OPEN_FEE', 'RENT_WAITING_FEE',
                'RENT_MINUTE_CHARGE', 'RENT_OVERTIME_FEE', 'RENT_DISTANCE_FEE',
                'RENT_BASE_CHARGE', 'RENT_FUEL_FEE', 'DELIVERY_FEE', 'DELIVERY_PENALTY',
                'MANUAL_ADJUSTMENT', 'ADMIN_DEDUCTION', 'DAMAGE_PENALTY', 'FINE_PENALTY', 'OWNER_WAITING_FEE_SHARE', 'SANCTION_PENALTY',
                'RESERVATION_REBOOKING_FEE', 'RENT_DRIVER_FEE'
            );

        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)


def create_users_table():
    """Create users table"""
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('last_name', sa.String(), nullable=True),
        sa.Column('middle_name', sa.String(100), nullable=True),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('birth_date', sa.DateTime(), nullable=True),
        sa.Column('iin', sa.String(12), nullable=True),
        sa.Column('passport_number', sa.String(50), nullable=True),
        sa.Column('drivers_license_expiry', sa.DateTime(), nullable=True),
        sa.Column('wallet_balance', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('selfie_with_license_url', sa.String(), nullable=True),
        sa.Column('selfie_url', sa.String(), nullable=True),
        sa.Column('drivers_license_url', sa.String(), nullable=True),
        sa.Column('id_card_front_url', sa.String(), nullable=True),
        sa.Column('id_card_back_url', sa.String(), nullable=True),
        sa.Column('id_card_expiry', sa.DateTime(), nullable=True),
        sa.Column('psych_neurology_certificate_url', sa.String(), nullable=True),
        sa.Column('narcology_certificate_url', sa.String(), nullable=True),
        sa.Column('pension_contributions_certificate_url', sa.String(), nullable=True),
        sa.Column('documents_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('role', postgresql.ENUM('admin', 'user', 'rejected', 'client', 'pending', 'mechanic', 'GARANT', 'financier', 'mvd', 'SUPPORT', 'PENDINGTOFIRST', 'PENDINGTOSECOND', 'REJECTFIRSTDOC', 'REJECTFIRSTCERT', 'REJECTFIRST', 'REJECTSECOND', 'ADMIN', 'USER', 'REJECTED', 'CLIENT', 'PENDING', 'MECHANIC', 'FINANCIER', 'MVD', name='userrole', create_type=False), nullable=False, server_default='client'),
        sa.Column('last_sms_code', sa.String(), nullable=True),
        sa.Column('sms_code_valid_until', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_verified_email', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_citizen_kz', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('fcm_token', sa.String(), nullable=True),
        sa.Column('locale', sa.String(), nullable=False, server_default="'ru'"),
        sa.Column('auto_class', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('digital_signature', sa.String(), nullable=True, unique=True),
        sa.Column('is_consent_to_data_processing', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_contract_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_user_agreement', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('can_exit_zone', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_activity_at', sa.DateTime(), nullable=True),
        sa.Column('upload_document_at', sa.DateTime(), nullable=True),
        sa.Column('admin_comment', sa.String(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True), 
        sa.UniqueConstraint('phone_number'),
        sa.UniqueConstraint('digital_signature')
    )


def create_user_devices_table():
    """Create user_devices table for tracking user devices and tokens"""
    op.create_table('user_devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_id', sa.String(128), nullable=True),
        sa.Column('fcm_token', sa.String(), nullable=True),
        sa.Column('platform', sa.String(32), nullable=True),
        sa.Column('model', sa.String(128), nullable=True),
        sa.Column('os_version', sa.String(64), nullable=True),
        sa.Column('app_version', sa.String(32), nullable=True),
        sa.Column('app_type', sa.String(32), nullable=True),
        sa.Column('last_ip', sa.String(64), nullable=True),
        sa.Column('last_lat', sa.Float(), nullable=True),
        sa.Column('last_lng', sa.Float(), nullable=True),
        sa.Column('last_active_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('device_id', name='uq_user_devices_device_id'),
        sa.UniqueConstraint('fcm_token', name='uq_user_devices_fcm_token')
    )
    op.create_index('ix_user_devices_user_id', 'user_devices', ['user_id'])


def create_tokens_table():
    """Create auth_tokens table"""
    op.create_table('auth_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_type', sa.String(20), nullable=False),
        sa.Column('token', sa.Text(), nullable=False, unique=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])
    op.create_index('ix_auth_tokens_token_type', 'auth_tokens', ['token_type'])
    op.create_index('ix_auth_tokens_token', 'auth_tokens', ['token'])

def create_cars_table():
    """Create cars table"""
    op.create_table('cars',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('plate_number', sa.String(), nullable=False, unique=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('gps_id', sa.String(), nullable=True),
        sa.Column('gps_imei', sa.String(), nullable=True),
        sa.Column('fuel_level', sa.Float(), nullable=True),
        sa.Column('mileage', sa.Integer(), nullable=True),
        sa.Column('course', sa.Integer(), nullable=True),
        sa.Column('price_per_minute', sa.Integer(), nullable=False),
        sa.Column('price_per_hour', sa.Integer(), nullable=False),
        sa.Column('price_per_day', sa.Integer(), nullable=False),
        sa.Column('car_class', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('auto_class', postgresql.ENUM('A', 'B', 'C', name='carautoclass', create_type=False), nullable=False, server_default='A'),
        sa.Column('engine_volume', sa.Float(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('drive_type', sa.Integer(), nullable=True),
        sa.Column('transmission_type', postgresql.ENUM('manual', 'automatic', 'cvt', 'semi_automatic', name='transmissiontype', create_type=False), nullable=True),
        sa.Column('body_type', postgresql.ENUM('SEDAN', 'SUV', 'CROSSOVER', 'COUPE', 'HATCHBACK', 'CONVERTIBLE', 'WAGON', 'MINIBUS', 'ELECTRIC', name='carbodytype', create_type=False), nullable=False, server_default='SEDAN'),
        sa.Column('vin', sa.String(), nullable=True),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('photos', postgresql.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('current_renter_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('status', postgresql.ENUM('FREE', 'PENDING', 'IN_USE', 'DELIVERING', 'SERVICE', 'RESERVED', 'SCHEDULED', 'OWNER', 'OCCUPIED', 'free', 'pending', 'in_use', 'delivering', 'service', 'reserved', 'scheduled', 'owner', 'occupied', name='carstatus', create_type=False), nullable=True, server_default='FREE'),
        sa.Column('available_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('availability_updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text('now()')),
        sa.Column('rating', sa.Float(), nullable=True) 
    )


def create_applications_table():
    """Create applications table"""
    op.create_table('applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('financier_status', postgresql.ENUM('pending', 'approved', 'rejected', name='applicationstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('financier_approved_at', sa.DateTime(), nullable=True),
        sa.Column('financier_rejected_at', sa.DateTime(), nullable=True),
        sa.Column('financier_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('mvd_status', postgresql.ENUM('pending', 'approved', 'rejected', name='applicationstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('mvd_approved_at', sa.DateTime(), nullable=True),
        sa.Column('mvd_rejected_at', sa.DateTime(), nullable=True),
        sa.Column('mvd_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_guarantor_requests_table():
    """Create guarantor_requests table"""
    op.create_table('guarantor_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('requestor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('guarantor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('guarantor_phone', sa.String(), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'accepted', 'rejected', 'expired', name='guarantorrequeststatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('verification_status', postgresql.ENUM('not_verified', 'verified', 'rejected', name='verificationstatus', create_type=False), nullable=False, server_default='not_verified'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True)
    )


def create_guarantors_table():
    """Create guarantors table"""
    op.create_table('guarantors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('guarantor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('guarantor_requests.id'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('deactivated_at', sa.DateTime(), nullable=True)
    )


def create_rental_history_table():
    """Create rental_history table"""
    op.create_table('rental_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('car_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cars.id'), nullable=False),
        sa.Column('rental_type', postgresql.ENUM('minutes', 'hours', 'days', name='rentaltype', create_type=False), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('start_latitude', sa.Float(), nullable=False),
        sa.Column('start_longitude', sa.Float(), nullable=False),
        sa.Column('end_latitude', sa.Float(), nullable=True),
        sa.Column('end_longitude', sa.Float(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('reservation_time', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('scheduled_start_time', sa.DateTime(), nullable=True),
        sa.Column('scheduled_end_time', sa.DateTime(), nullable=True),
        sa.Column('is_advance_booking', sa.String(), nullable=False, server_default='false'),
        sa.Column('base_price', sa.Integer(), nullable=True),
        sa.Column('open_fee', sa.Integer(), nullable=True),
        sa.Column('delivery_fee', sa.Integer(), nullable=True),
        sa.Column('waiting_fee', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('overtime_fee', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('distance_fee', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('photos_before', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('photos_after', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('fuel_before', sa.Float(), nullable=True),
        sa.Column('fuel_after', sa.Float(), nullable=True),
        sa.Column('fuel_after_main_tariff', sa.Float(), nullable=True),
        sa.Column('mileage_before', sa.Integer(), nullable=True),
        sa.Column('mileage_after', sa.Integer(), nullable=True),
        sa.Column('already_payed', sa.Integer(), nullable=True),
        sa.Column('total_price', sa.Integer(), nullable=True),
        sa.Column('rental_status', postgresql.ENUM('reserved', 'in_use', 'completed', 'delivering', 'delivering_in_progress', 'delivery_reserved', 'cancelled', 'scheduled', 'RESERVED', 'IN_USE', 'COMPLETED', 'DELIVERING', 'DELIVERING_IN_PROGRESS', 'DELIVERY_RESERVED', 'CANCELLED', 'SCHEDULED', name='rentalstatus', create_type=False), nullable=False, server_default='reserved'),
        sa.Column('delivery_latitude', sa.Float(), nullable=True),
        sa.Column('delivery_longitude', sa.Float(), nullable=True),
        sa.Column('delivery_mechanic_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('delivery_start_time', sa.DateTime(), nullable=True),
        sa.Column('delivery_end_time', sa.DateTime(), nullable=True),
        sa.Column('delivery_penalty_fee', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('delivery_start_latitude', sa.Float(), nullable=True),
        sa.Column('delivery_start_longitude', sa.Float(), nullable=True),
        sa.Column('delivery_end_latitude', sa.Float(), nullable=True),
        sa.Column('delivery_end_longitude', sa.Float(), nullable=True),
        sa.Column('delivery_photos_before', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('delivery_photos_after', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('mechanic_photos_before', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('mechanic_photos_after', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('mechanic_inspector_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('mechanic_inspection_start_time', sa.DateTime(), nullable=True),
        sa.Column('mechanic_inspection_end_time', sa.DateTime(), nullable=True),
        sa.Column('mechanic_inspection_status', sa.String(), nullable=True, server_default='PENDING'),
        sa.Column('mechanic_inspection_comment', sa.Text(), nullable=True),
        sa.Column('mechanic_inspection_start_latitude', sa.Float(), nullable=True),
        sa.Column('mechanic_inspection_start_longitude', sa.Float(), nullable=True),
        sa.Column('mechanic_inspection_end_latitude', sa.Float(), nullable=True),
        sa.Column('mechanic_inspection_end_longitude', sa.Float(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('with_driver', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('driver_fee', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('rebooking_fee', sa.Integer(), nullable=True, server_default='0')
    )


def create_rental_reviews_table():
    """Create rental_reviews table"""
    op.create_table('rental_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('rental_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rental_history.id'), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('comment', sa.String(255), nullable=True),
        sa.Column('mechanic_rating', sa.Integer(), nullable=True),
        sa.Column('mechanic_comment', sa.String(255), nullable=True),
        sa.Column('delivery_mechanic_rating', sa.Integer(), nullable=True),
        sa.Column('delivery_mechanic_comment', sa.String(255), nullable=True)
    )


def create_rental_actions_table():
    """Create rental_actions table"""
    op.create_table('rental_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('rental_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rental_history.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action_type', postgresql.ENUM('open_vehicle', 'close_vehicle', 'give_key', 'take_key', 'lock_engine', 'unlock_engine', name='actiontype', create_type=False), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_car_comments_table():
    """Create car_comments table"""
    op.create_table('car_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('car_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cars.id'), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_verification_codes_table():
    """Create verification_codes table"""
    op.create_table('verification_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('phone_number', sa.String(50), nullable=True),
        sa.Column('email', sa.String(50), nullable=True),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('purpose', sa.String(50), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('expires_at', sa.DateTime(), nullable=False)
    )


def create_contract_files_table():
    """Create contract_files table"""
    op.create_table('contract_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('contract_type', postgresql.ENUM('guarantor_contract', 'guarantor_main_contract', 'user_agreement', 'consent_to_data_processing', 'main_contract', 'rental_main_contract', 'appendix_7_1', 'appendix_7_2', 'GUARANTOR_CONTRACT', 'GUARANTOR_MAIN_CONTRACT', 'USER_AGREEMENT', 'CONSENT_TO_DATA_PROCESSING', 'MAIN_CONTRACT', 'RENTAL_MAIN_CONTRACT', 'APPENDIX_7_1', 'APPENDIX_7_2', name='contracttype', create_type=False), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_user_contract_signatures_table():
    """Create user_contract_signatures table"""
    op.create_table('user_contract_signatures',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('contract_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contract_files.id'), nullable=False),
        sa.Column('rental_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rental_history.id'), nullable=True),
        sa.Column('guarantor_relationship_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('guarantors.id'), nullable=True),
        sa.Column('digital_signature', sa.String(), nullable=False),
        sa.Column('signed_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_notifications_table():
    """Create notifications table"""
    op.create_table('notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', postgresql.ENUM('mechanic_assigned', 'car_delivered', 'delivery_new_order', 'delivery_started', 'new_car_for_inspection', 'paid_waiting_soon', 'paid_waiting_started', 'low_balance', 'basic_tariff_ending_soon', 'out_of_tariff_charges', 'delivery_cancelled', 'balance_exhausted', 'delivery_delay_penalty', 'documents_recheck_required', 'application_rejected_financier', 'application_rejected_mvd', 'application_approved_financier', 'application_approved_mvd', 'guarantor_invitation', 'guarantor_accepted', 'fuel_empty', 'account_balance_low', 'zone_exit', 'rpm_spikes', 'verification_passed', 'verification_failed', 'promo_code_available', 'guarantor_connected', 'fuel_refill_detected', 'courier_found', 'courier_delivered', 'fine_issued', 'balance_top_up', 'basic_tariff_ending', 'locks_open', 'impact_weak', 'impact_medium', 'impact_strong', 'birthday', 'friday_evening', 'monday_morning', 'new_car_available', 'car_nearby', 'holiday_greeting', 'airport_location', 'car_viewed_exit', 'documents_uploaded', 'email_verification_required', 'missing_documents_bonus', 'rental_extended', 'MECHANIC_ASSIGNED', 'CAR_DELIVERED', 'DELIVERY_NEW_ORDER', 'DELIVERY_STARTED', 'NEW_CAR_FOR_INSPECTION', 'PAID_WAITING_SOON', 'PAID_WAITING_STARTED', 'LOW_BALANCE', 'BASIC_TARIFF_ENDING_SOON', 'OUT_OF_TARIFF_CHARGES', 'DELIVERY_CANCELLED', 'BALANCE_EXHAUSTED', 'DELIVERY_DELAY_PENALTY', 'DOCUMENTS_RECHECK_REQUIRED', 'APPLICATION_REJECTED_FINANCIER', 'APPLICATION_REJECTED_MVD', 'APPLICATION_APPROVED_FINANCIER', 'APPLICATION_APPROVED_MVD', 'GUARANTOR_INVITATION', 'GUARANTOR_ACCEPTED', 'FUEL_EMPTY', 'ACCOUNT_BALANCE_LOW', 'ZONE_EXIT', 'RPM_SPIKES', 'VERIFICATION_PASSED', 'VERIFICATION_FAILED', 'PROMO_CODE_AVAILABLE', 'GUARANTOR_CONNECTED', 'FUEL_REFILL_DETECTED', 'COURIER_FOUND', 'COURIER_DELIVERED', 'FINE_ISSUED', 'BALANCE_TOP_UP', 'BASIC_TARIFF_ENDING', 'LOCKS_OPEN', 'IMPACT_WEAK', 'IMPACT_MEDIUM', 'IMPACT_STRONG', 'BIRTHDAY', 'FRIDAY_EVENING', 'MONDAY_MORNING', 'NEW_CAR_AVAILABLE', 'CAR_NEARBY', 'HOLIDAY_GREETING', 'AIRPORT_LOCATION', 'CAR_VIEWED_EXIT', 'DOCUMENTS_UPLOADED', 'EMAIL_VERIFICATION_REQUIRED', 'MISSING_DOCUMENTS_BONUS', 'RENTAL_EXTENDED', name='notificationstatus', create_type=False), nullable=True)
    )


def create_promo_codes_table():
    """Create promo_codes table"""
    op.create_table('promo_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('discount_percent', sa.Numeric(5, 2), nullable=False, server_default='15'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_user_promo_codes_table():
    """Create user_promo_codes table"""
    op.create_table('user_promo_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('promo_code_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('promo_codes.id'), nullable=False),
        sa.Column('status', postgresql.ENUM('activated', 'used', name='userpromostatus', create_type=False), nullable=False, server_default='activated'),
        sa.Column('activated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('used_at', sa.DateTime(), nullable=True)
    )


def create_support_actions_table():
    """Create support_actions table"""
    op.create_table('support_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(128), nullable=False),
        sa.Column('entity_type', sa.String(64), nullable=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_wallet_transactions_table():
    """Create wallet_transactions table"""
    op.create_table('wallet_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('transaction_type', postgresql.ENUM('deposit', 'promo_bonus', 'refund', 'rent_open_fee', 'rent_waiting_fee', 'rent_minute_charge', 'rent_overtime_fee', 'rent_distance_fee', 'rent_base_charge', 'rent_fuel_fee', 'delivery_fee', 'delivery_penalty', 'manual_adjustment', 'damage_penalty', 'fine_penalty', name='wallettransactiontype', create_type=False), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('balance_before', sa.Numeric(10, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(10, 2), nullable=False),
        sa.Column('related_rental_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rental_history.id'), nullable=True),
        sa.Column('tracking_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )
    
    op.create_index('idx_wallet_transactions_tracking_id', 'wallet_transactions', ['tracking_id'], unique=True, postgresql_where=sa.text('tracking_id IS NOT NULL'))

def create_support_chats_table():
    """Create support_chats table"""
    op.create_table('support_chats',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('user_telegram_username', sa.String(255), nullable=True),
        sa.Column('user_name', sa.String(255), nullable=False),
        sa.Column('user_phone', sa.String(20), nullable=False),
        sa.Column('azv_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(), nullable=True)
    )
    
    # Create indexes for support_chats
    op.create_index('ix_support_chats_id', 'support_chats', ['id'])
    op.create_index('ix_support_chats_user_telegram_id', 'support_chats', ['user_telegram_id'])
    op.create_index('ix_support_chats_user_phone', 'support_chats', ['user_phone'])
    op.create_index('ix_support_chats_status', 'support_chats', ['status'])


def create_support_messages_table():
    """Create support_messages table"""
    op.create_table('support_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('chat_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('support_chats.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_type', sa.String(20), nullable=False),
        sa.Column('sender_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('is_from_bot', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('media_type', sa.String(20), nullable=True),
        sa.Column('media_url', sa.String(512), nullable=True),
        sa.Column('media_file_name', sa.String(255), nullable=True),
        sa.Column('media_file_size', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )
    
    # Create indexes for support_messages
    op.create_index('ix_support_messages_id', 'support_messages', ['id'])
    op.create_index('ix_support_messages_chat_id', 'support_messages', ['chat_id'])
    op.create_index('ix_support_messages_sender_type', 'support_messages', ['sender_type'])


def create_app_versions_table():
    """Create app_versions table for storing app version information"""
    op.create_table('app_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('android_version', sa.String(64), nullable=True),
        sa.Column('ios_version', sa.String(64), nullable=True),
        sa.Column('ios_link', sa.String(512), nullable=True),
        sa.Column('android_link', sa.String(512), nullable=True),
        sa.Column('ai_is_worked', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )


def create_car_availability_history_table():
    """Create car_availability_history table"""
    op.create_table('car_availability_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('car_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cars.id'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('available_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now())
    )


def downgrade() -> None:
    # Drop all tables in reverse order
    # Drop indexes first (with existence check)
    op.drop_table('car_availability_history')
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_auth_tokens_token') THEN
                DROP INDEX ix_auth_tokens_token;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_auth_tokens_token_type') THEN
                DROP INDEX ix_auth_tokens_token_type;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_auth_tokens_user_id') THEN
                DROP INDEX ix_auth_tokens_user_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_wallet_transactions_tracking_id') THEN
                DROP INDEX idx_wallet_transactions_tracking_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_messages_sender_type') THEN
                DROP INDEX ix_support_messages_sender_type;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_messages_chat_id') THEN
                DROP INDEX ix_support_messages_chat_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_messages_id') THEN
                DROP INDEX ix_support_messages_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_chats_status') THEN
                DROP INDEX ix_support_chats_status;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_chats_user_phone') THEN
                DROP INDEX ix_support_chats_user_phone;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_chats_user_telegram_id') THEN
                DROP INDEX ix_support_chats_user_telegram_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_support_chats_id') THEN
                DROP INDEX ix_support_chats_id;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_user_devices_user_id') THEN
                DROP INDEX ix_user_devices_user_id;
            END IF;
        END $$;
    """)
    # Drop tokens table early due to FK to users
    op.drop_table('auth_tokens')
    op.drop_table('app_versions')
    op.drop_table('support_messages')
    op.drop_table('support_chats')
    op.drop_table('wallet_transactions')
    op.drop_table('support_actions')
    op.drop_table('user_promo_codes')
    op.drop_table('promo_codes')
    op.drop_table('notifications')
    op.drop_table('user_contract_signatures')
    op.drop_table('contract_files')
    op.drop_table('verification_codes')
    op.drop_table('car_comments')
    op.drop_table('rental_actions')
    op.drop_table('rental_reviews')
    op.drop_table('rental_history')
    op.drop_table('guarantors')
    op.drop_table('guarantor_requests')
    op.drop_table('applications')
    op.drop_table('cars')
    op.drop_table('user_devices')
    op.drop_table('users')
    
    # Drop all enums
    enums_to_drop = [
        'wallettransactiontype', 'userpromostatus', 'notificationstatus', 'contracttype',
        'actiontype', 'rentalstatus', 'rentaltype', 'verificationstatus',
        'guarantorrequeststatus', 'applicationstatus', 'carstatus', 'transmissiontype',
        'carautoclass', 'carbodytype', 'autoclass', 'userrole'
    ]
    
    for enum_name in enums_to_drop:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
