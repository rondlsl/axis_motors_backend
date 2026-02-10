from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.logging_config import get_logger
from app.partnership.schemas import PartnershipRequest, PartnershipResponse
from app.partnership.service import send_partnership_to_bot

logger = get_logger(__name__)

partnership_router = APIRouter(prefix="/partnership", tags=["Partnership"])


@partnership_router.post("/request", response_model=PartnershipResponse)
async def create_partnership_request(
    request_data: PartnershipRequest,
    background_tasks: BackgroundTasks
):
    """
    Создать заявку на сотрудничество.
    Заявка будет отправлена в Telegram бот.
    """
    try:
        # Отправляем в бот в фоновом режиме
        background_tasks.add_task(send_partnership_to_bot, request_data)
        
        return PartnershipResponse(
            message="Заявка на сотрудничество успешно отправлена! Мы свяжемся с вами в ближайшее время.",
            success=True
        )
        
    except Exception as e:
        logger.error(f"Error creating partnership request: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Ошибка отправки заявки. Пожалуйста, попробуйте позже.",
                "success": False
            }
        )


@partnership_router.get("/")
async def partnership_info():
    """
    Информация о партнерстве.
    """
    return {
        "message": "Форма для заявок на сотрудничество",
        "endpoint": "POST /partnership/request",
        "description": "Отправьте заявку для обсуждения возможностей сотрудничества"
    }
