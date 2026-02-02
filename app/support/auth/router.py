from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import traceback

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_support
from app.models.user_model import User
from app.core.logging_config import get_logger

logger = get_logger(__name__)


support_auth_router = APIRouter(tags=["Support Auth"])


@support_auth_router.get("/user/me")
async def support_read_users_me(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_support)
):
    """
    Эндпоинт профиля поддержки (SUPPORT).
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
        logger.error(f"Error in /support/auth/user/me: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
