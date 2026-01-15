from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import traceback

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_accountant
from app.models.user_model import User
from app.core.config import logger


accountant_auth_router = APIRouter(tags=["Accountant Auth"])


@accountant_auth_router.get("/user/me")
async def accountant_read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_accountant)
):
    """
    Эндпоинт профиля бухгалтера
    """
    try:
        from app.utils.user_data import get_user_me_data
        return await get_user_me_data(db, current_user)
    except HTTPException as e:
        if e.status_code in [401, 403]:
            raise e
        else:
            raise HTTPException(status_code=401, detail="Authentication failed")
    except Exception as e:
        logger.error(f"Error in /accountant/auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")

