from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import traceback

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_user
from app.models.user_model import User, UserRole
from app.core.config import logger


admin_auth_router = APIRouter(tags=["Admin Auth"])


@admin_auth_router.get("/user/me")
async def admin_read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Эндпоинт профиля администратора
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    try:
        from app.utils.user_data import get_user_me_data
        return await get_user_me_data(db, current_user)
    except HTTPException as e:
        if e.status_code in [401, 403]:
            raise e
        else:
            raise HTTPException(status_code=401, detail="Authentication failed")
    except Exception as e:
        logger.error(f"Error in /admin/auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


