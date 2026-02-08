from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.auth.dependencies.get_current_user import get_current_user
from app.dependencies.database.database import get_db
from app.models.user_model import User
from app.promo.schemas import PromoApplyRequest, PromoApplyResponse
from app.promo.service import apply_promo_code

logger = get_logger(__name__)

PromoRouter = APIRouter(tags=["Promo"], prefix="/promo")


@PromoRouter.post("/apply", response_model=PromoApplyResponse)
async def apply_promo(
    body: PromoApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Применить бонусный промокод.

    - 200 — успешно применён
    - 400 — промокод недоступен / истёк / условия не выполнены
    - 409 — уже использован
    """
    success, message, bonus_amount, new_balance = await apply_promo_code(
        db, current_user, body.code,
    )

    if not success:
        # Различаем «уже использован» (409) и прочие ошибки (400)
        if "уже использовали" in message:
            raise HTTPException(status_code=409, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return PromoApplyResponse(
        message=message,
        bonus_amount=bonus_amount,
        new_balance=new_balance,
    )
