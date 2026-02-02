from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies.database.database import get_db
from app.auth.dependencies.get_current_user import get_current_support
from app.models.user_model import User
from app.admin.cars.schemas import CarDetailSchema
from app.admin.cars.router import get_car_details_response

support_cars_router = APIRouter(tags=["Support Cars"])


@support_cars_router.get("/{car_id}/details", response_model=CarDetailSchema)
async def get_car_details_support(
    car_id: str,
    current_user: User = Depends(get_current_support),
    db: Session = Depends(get_db),
) -> CarDetailSchema:
    """Получить детальную информацию об автомобиле (для роли SUPPORT)."""
    return await get_car_details_response(car_id, db)
