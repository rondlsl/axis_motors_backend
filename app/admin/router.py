from fastapi import APIRouter
from app.admin.cars.router import cars_router
from app.admin.guarantors.router import guarantors_router
from app.admin.users.router import users_router

admin_router = APIRouter(prefix="/admin", tags=["Admin"])

admin_router.include_router(cars_router, prefix="/cars")
admin_router.include_router(guarantors_router, prefix="/guarantors")
admin_router.include_router(users_router, prefix="/users")

router = admin_router
