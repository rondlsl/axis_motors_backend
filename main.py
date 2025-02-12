from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from starlette.middleware.cors import CORSMiddleware

from app.auth.router import Auth_router
from app.gps_api.monitoring.monitoring import VehicleMonitor
from app.gps_api.router import Vehicle_Router, get_vehicle_by_id
from app.rent.router import RentRouter

vehicle_monitor = VehicleMonitor()
scheduler = AsyncIOScheduler()


async def check_vehicle_conditions():
    try:
        result = get_vehicle_by_id(868184066093710)
        if result:
            vehicle_monitor.check_conditions(result)
    except Exception as e:
        print(f"Error checking vehicle conditions: {e}")


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        scheduler.add_job(check_vehicle_conditions, 'interval', seconds=10, id='vehicle_monitor')
        scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event():
        await scheduler.shutdown()


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_app(app)
app.include_router(Auth_router)
app.include_router(Vehicle_Router)
app.include_router(RentRouter)


@app.get("/")
def root():
    return {"message": "че надо тут?"}
