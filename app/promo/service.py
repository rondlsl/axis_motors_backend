"""
Сервис бонусных промокодов.

Redis-ключи:
  promo:active:{code}            — JSON с данными активного промокода (TTL = до valid_to)
  promo:used:{user_id}:{code}    — флаг «пользователь уже активировал» (TTL 30 дней)
  promo:apply_lock:{user_id}     — idempotency lock на активацию (TTL 10 сек)
  promo:rate:{user_id}           — счётчик запросов /promo/apply за минуту (TTL 60 сек)
"""
import json
import logging
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bonus_promo_model import BonusPromoCode, BonusPromoUsage
from app.models.wallet_transaction_model import WalletTransaction, WalletTransactionType
from app.models.user_model import User
from app.services.redis_service import get_redis_service
from app.wallet.utils import record_wallet_transaction
from app.utils.time_utils import get_local_time
from app.utils.short_id import uuid_to_sid

logger = logging.getLogger(__name__)

# ─── Redis key builders ──────────────────────────────────────────────

PROMO_ACTIVE_PREFIX = "promo:active:"
PROMO_USED_PREFIX = "promo:used:"
PROMO_LOCK_PREFIX = "promo:apply_lock:"
PROMO_RATE_PREFIX = "promo:rate:"

PROMO_CACHE_TTL = 300           # 5 мин кэш активного промокода
PROMO_USED_TTL = 60 * 60 * 24 * 30  # 30 дней
PROMO_LOCK_TTL = 10             # 10 сек idempotency
PROMO_RATE_WINDOW = 60          # 1 мин
PROMO_RATE_LIMIT = 5            # макс 5 попыток в минуту


def _active_key(code: str) -> str:
    return f"{PROMO_ACTIVE_PREFIX}{code.upper()}"


def _used_key(user_id, code: str) -> str:
    return f"{PROMO_USED_PREFIX}{user_id}:{code.upper()}"


def _lock_key(user_id) -> str:
    return f"{PROMO_LOCK_PREFIX}{user_id}"


def _rate_key(user_id) -> str:
    return f"{PROMO_RATE_PREFIX}{user_id}"


# ─── Cache helpers ───────────────────────────────────────────────────

async def _cache_promo(promo: BonusPromoCode) -> None:
    """Кэшировать активный промокод в Redis."""
    redis = get_redis_service()
    if not redis.is_available:
        return
    now = get_local_time()
    ttl = max(int((promo.valid_to - now).total_seconds()), 60)
    data = json.dumps({
        "id": str(promo.id),
        "code": promo.code,
        "bonus_amount": promo.bonus_amount,
        "valid_from": promo.valid_from.isoformat(),
        "valid_to": promo.valid_to.isoformat(),
        "max_uses": promo.max_uses,
        "used_count": promo.used_count,
        "is_active": promo.is_active,
    })
    await redis.set(_active_key(promo.code), data, ttl=min(ttl, PROMO_CACHE_TTL))


async def _get_cached_promo(code: str) -> Optional[dict]:
    """Получить промокод из Redis-кэша."""
    redis = get_redis_service()
    raw = await redis.get(_active_key(code))
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


async def _invalidate_promo_cache(code: str) -> None:
    """Удалить кэш промокода."""
    redis = get_redis_service()
    await redis.delete(_active_key(code))


async def _mark_used_in_redis(user_id, code: str) -> None:
    """Пометить в Redis, что пользователь уже использовал промокод."""
    redis = get_redis_service()
    await redis.set(_used_key(user_id, code), "1", ttl=PROMO_USED_TTL)


async def _is_used_in_redis(user_id, code: str) -> bool:
    """Быстрая проверка: использовал ли пользователь промокод (по Redis)."""
    redis = get_redis_service()
    return await redis.exists(_used_key(user_id, code))


# ─── Rate limiting ───────────────────────────────────────────────────

async def check_rate_limit(user_id) -> bool:
    """
    Проверить rate limit на активацию промокодов.
    Returns True если лимит НЕ превышен (можно продолжать).
    """
    redis = get_redis_service()
    if not redis.is_available:
        return True  # graceful degradation
    key = _rate_key(user_id)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, PROMO_RATE_WINDOW)
    return count <= PROMO_RATE_LIMIT


# ─── Core business logic ────────────────────────────────────────────

async def apply_promo_code(
    db: Session,
    user: User,
    code: str,
) -> Tuple[bool, str, Optional[int], Optional[float]]:
    """
    Применить бонусный промокод.

    Returns:
        (success, message, bonus_amount, new_balance)
        При ошибке bonus_amount и new_balance = None.
    """
    code_upper = code.strip().upper()

    # 1) Rate limit
    if not await check_rate_limit(user.id):
        return False, "Слишком много попыток. Подождите минуту.", None, None

    # 2) Idempotency lock — защита от двойного нажатия
    redis = get_redis_service()
    lock_acquired = await redis.set(_lock_key(user.id), "1", ttl=PROMO_LOCK_TTL, nx=True)
    if redis.is_available and not lock_acquired:
        return False, "Запрос уже обрабатывается. Подождите.", None, None

    try:
        # 3) Быстрая проверка по Redis: уже использовал?
        if await _is_used_in_redis(user.id, code_upper):
            return False, "Вы уже использовали этот промокод.", None, None

        # 4) Загрузка промокода (сначала кэш, затем БД)
        cached = await _get_cached_promo(code_upper)
        now = get_local_time()

        if cached:
            # Быстрая pre-validation по кэшу
            from datetime import datetime
            vf = datetime.fromisoformat(cached["valid_from"])
            vt = datetime.fromisoformat(cached["valid_to"])
            if not cached["is_active"] or now < vf or now > vt:
                return False, "Промокод недоступен или срок действия истёк.", None, None
            if cached["max_uses"] is not None and cached["used_count"] >= cached["max_uses"]:
                return False, "Промокод исчерпал лимит использований.", None, None

        # 5) Атомарная операция в БД — SELECT … FOR UPDATE
        promo = (
            db.query(BonusPromoCode)
            .filter(
                func.upper(BonusPromoCode.code) == code_upper,
                BonusPromoCode.is_active == True,
            )
            .with_for_update()
            .first()
        )

        if promo is None:
            return False, "Промокод не найден.", None, None

        # 6) Проверка дат
        if now < promo.valid_from or now > promo.valid_to:
            return False, "Промокод недоступен или срок действия истёк.", None, None

        # 7) Проверка лимита использований
        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            return False, "Промокод исчерпал лимит использований.", None, None

        # 8) Проверка: пользователь уже активировал этот промокод? (БД — source of truth)
        existing_usage = (
            db.query(BonusPromoUsage)
            .filter(
                BonusPromoUsage.user_id == user.id,
                BonusPromoUsage.promo_code_id == promo.id,
            )
            .first()
        )
        if existing_usage:
            # Обновить Redis-кэш
            await _mark_used_in_redis(user.id, code_upper)
            return False, "Вы уже использовали этот промокод.", None, None

        # 9) Проверка: у пользователя 0 транзакций (ни одной записи в wallet_transactions)
        tx_count = (
            db.query(func.count(WalletTransaction.id))
            .filter(WalletTransaction.user_id == user.id)
            .scalar()
        )
        if tx_count > 0:
            return False, "Промокод доступен только для новых пользователей без транзакций.", None, None

        # 10) Начисление бонуса
        balance_before = float(user.wallet_balance or 0)
        new_balance = balance_before + promo.bonus_amount
        user.wallet_balance = new_balance

        # 11) Создание транзакции
        record_wallet_transaction(
            db,
            user=user,
            amount=promo.bonus_amount,
            ttype=WalletTransactionType.PROMO_BONUS,
            description=f"Бонус по промокоду «{promo.code}»",
            balance_before_override=balance_before,
        )

        # 12) Запись в PromoCodeUsage
        usage = BonusPromoUsage(
            user_id=user.id,
            promo_code_id=promo.id,
            used_at=now,
        )
        db.add(usage)

        # 13) Инкремент used_count
        promo.used_count = (promo.used_count or 0) + 1

        # 14) Атомарный коммит
        db.commit()

        # 15) Обновить Redis
        await _mark_used_in_redis(user.id, code_upper)
        await _invalidate_promo_cache(code_upper)

        logger.info(
            "Промокод %s применён: user=%s, bonus=%s, new_balance=%s",
            promo.code, user.id, promo.bonus_amount, new_balance,
        )

        return True, "Промокод успешно применён!", promo.bonus_amount, new_balance

    except Exception:
        db.rollback()
        raise
    finally:
        # Освобождаем idempotency lock
        await redis.delete(_lock_key(user.id))


# ─── Admin helpers ───────────────────────────────────────────────────

async def create_promo_code(
    db: Session,
    *,
    code: str,
    description: Optional[str],
    bonus_amount: int,
    valid_from,
    valid_to,
    max_uses: Optional[int],
) -> BonusPromoCode:
    """Создать новый бонусный промокод."""
    promo = BonusPromoCode(
        code=code.strip(),
        description=description,
        bonus_amount=bonus_amount,
        valid_from=valid_from,
        valid_to=valid_to,
        max_uses=max_uses,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)

    # Кэшируем
    await _cache_promo(promo)

    return promo


def get_promo_list(db: Session, *, limit: int = 100, offset: int = 0):
    """Список промокодов с подсчётом уникальных пользователей."""
    promos = (
        db.query(BonusPromoCode)
        .order_by(BonusPromoCode.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(func.count(BonusPromoCode.id)).scalar()
    return promos, total


def get_promo_detail(db: Session, promo_id):
    """Детальная информация о промокоде + список использований."""
    promo = db.query(BonusPromoCode).filter(BonusPromoCode.id == promo_id).first()
    if not promo:
        return None, []
    usages = (
        db.query(BonusPromoUsage)
        .filter(BonusPromoUsage.promo_code_id == promo.id)
        .order_by(BonusPromoUsage.used_at.desc())
        .all()
    )
    return promo, usages


def get_unique_users_count(db: Session, promo_id) -> int:
    """Количество уникальных пользователей, применивших промокод."""
    return (
        db.query(func.count(func.distinct(BonusPromoUsage.user_id)))
        .filter(BonusPromoUsage.promo_code_id == promo_id)
        .scalar()
    ) or 0
