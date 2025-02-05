import telebot
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import json
from typing import Optional, Dict, Any
import asyncio

from starlette.middleware.cors import CORSMiddleware

from app.auth.router import Auth_router
from app.gps_api.router import Vehicle_Router, get_vehicle_by_id
from app.rent.router import RentRouter

# Initialize bot with your token
bot = telebot.TeleBot('7649836420:AAHJkjRAlMOe2NWqK_UIkYXlFBx07BCFXlY')

# Target user ID for notifications
TARGET_USER_ID = 965048905


class VehicleMonitor:
    def extract_value(self, data: Dict[str, Any], key: str, sensors_list: str) -> Optional[float]:
        """Extract numeric value from sensors, handling different formats."""
        try:
            for sensor in data['vehicle'].get(sensors_list, []):
                if key.lower() in sensor['name'].lower():
                    # Try to extract numeric value from string
                    value_str = str(sensor['value']).split()[0]  # Take first part before any units
                    value_str = value_str.replace(',', '.')  # Handle comma decimals
                    if value_str.lower() in ['данных нет', '-', 'нет данных']:
                        return None
                    return float(value_str)
            return None
        except (ValueError, KeyError, TypeError):
            return None

    def check_conditions(self, data: Dict[str, Any]):
        """Check all monitored conditions and send alerts if needed."""
        alerts = []

        # Проверяем скорость
        speed = self.extract_value(data, 'скорость', 'GeneralSensors') or \
                self.extract_value(data, 'скорость', 'RegistredSensors')
        if speed is not None and speed >= 100:
            alerts.append(f"⚠️ Превышение скорости: {speed} км/ч")

        # Проверяем обороты
        rpm = self.extract_value(data, 'обороты', 'RegistredSensors')
        if rpm is not None and rpm >= 4000:
            alerts.append(f"⚠️ Высокие обороты двигателя: {rpm} об/мин")

        # Проверяем капот
        hood_sensor = next((s for s in data['vehicle'].get('RegistredSensors', [])
                            if 'капот' in s['name'].lower()), None)
        if hood_sensor and 'открыт' in hood_sensor['value'].lower():
            alerts.append("⚠️ Капот открыт!")

        # Проверяем температуру
        temp = self.extract_value(data, 'температура двигателя', 'RegistredSensors')
        if temp is not None and temp >= 100:
            alerts.append(f"⚠️ Высокая температура двигателя: {temp}°C")

        if alerts:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            message = f"🚗 Внимание! {timestamp}\n\n" + "\n".join(alerts)
            try:
                bot.send_message(TARGET_USER_ID, message)
                bot.send_message(5941825713, message)
            except Exception as e:
                print(f"Failed to send Telegram message: {e}")


vehicle_monitor = VehicleMonitor()

# Create scheduler
scheduler = AsyncIOScheduler()


async def check_vehicle_conditions():
    """Function to check vehicle conditions periodically."""
    try:
        # Use your existing get_vehicle_by_id function
        result = get_vehicle_by_id(868184066093710)  # Replace with actual vehicle ID
        if result:
            vehicle_monitor.check_conditions(result)
    except Exception as e:
        print(f"Error checking vehicle conditions: {e}")


def init_app(app: FastAPI):
    @app.on_event("startup")
    async def startup_event():
        # Start the scheduler
        scheduler.add_job(check_vehicle_conditions, 'interval', seconds=10, id='vehicle_monitor')
        scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event():
        await scheduler.shutdown()


# Update your main FastAPI app
app = FastAPI()
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the monitoring system
init_app(app)

app.include_router(Auth_router)
app.include_router(Vehicle_Router)
app.include_router(RentRouter)


@app.get("/")
def root():
    return dict(message="че надо тут?")
