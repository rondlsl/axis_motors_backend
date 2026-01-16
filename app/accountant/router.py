from fastapi import APIRouter
from app.accountant.auth.router import accountant_auth_router
from app.accountant.rentals.router import accountant_rentals_router

accountant_router = APIRouter(prefix="/accountant")

accountant_router.include_router(accountant_auth_router, prefix="/auth")
accountant_router.include_router(accountant_rentals_router, prefix="/rentals")

router = accountant_router

