from fastapi import APIRouter
from app.admin.cars.router import cars_router
from app.admin.guarantors.router import guarantors_router
from app.admin.users.router import users_router
from app.admin.support.router import support_router
from app.admin.sms.router import sms_router
from app.admin.auth.router import admin_auth_router
from app.admin.app_versions.router import router as app_versions_admin_router

admin_router = APIRouter(prefix="/admin")

admin_router.include_router(cars_router, prefix="/cars")
admin_router.include_router(guarantors_router, prefix="/guarantors")
admin_router.include_router(users_router, prefix="/users")
admin_router.include_router(support_router, prefix="/support")
admin_router.include_router(sms_router, prefix="/sms")
admin_router.include_router(admin_auth_router, prefix="/auth")
admin_router.include_router(app_versions_admin_router, prefix="/app-versions")

router = admin_router
