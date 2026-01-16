from fastapi import APIRouter
from app.accountant.auth.router import accountant_auth_router
from app.accountant.rentals.router import accountant_rentals_router
from app.accountant.analytics.router import accountant_analytics_router, accountant_transactions_router

accountant_router = APIRouter(prefix="/accountant")

accountant_router.include_router(accountant_auth_router, prefix="/auth")
accountant_router.include_router(accountant_rentals_router, prefix="/rentals")
accountant_router.include_router(accountant_analytics_router)
accountant_router.include_router(accountant_transactions_router)

router = accountant_router

