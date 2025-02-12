import datetime
from typing import Dict, Any, Optional

import telebot

from app.core.config import POLYGON_COORDS
from app.gps_api.utils.point_in_polygon import is_point_inside_polygon

bot = telebot.TeleBot('7649836420:AAHJkjRAlMOe2NWqK_UIkYXlFBx07BCFXlY')
TARGET_USER_ID = 965048905


class VehicleMonitor:
    def extract_value(self, data: Dict[str, Any], key: str, sensors_list: str) -> Optional[float]:
        try:
            for sensor in data['vehicle'].get(sensors_list, []):
                if key.lower() in sensor['name'].lower():
                    value_str = str(sensor['value']).split()[0].replace(',', '.')
                    if value_str.lower() in ['данных нет', '-', 'нет данных']:
                        return None
                    return float(value_str)
            return None
        except (ValueError, KeyError, TypeError):
            return None

    def check_conditions(self, data: Dict[str, Any]):
        alerts = []

        speed = self.extract_value(data, 'скорость', 'GeneralSensors') or \
                self.extract_value(data, 'скорость', 'RegistredSensors')
        if speed is not None and speed >= 100:
            alerts.append(f"⚠️ Превышение скорости: {speed} км/ч")

        rpm = self.extract_value(data, 'обороты', 'RegistredSensors')
        if rpm is not None and rpm >= 4000:
            alerts.append(f"⚠️ Высокие обороты двигателя: {rpm} об/мин")

        hood_sensor = next((s for s in data['vehicle'].get('RegistredSensors', [])
                            if 'капот' in s['name'].lower()), None)
        if hood_sensor and 'открыт' in hood_sensor['value'].lower():
            alerts.append("⚠️ Капот открыт!")

        temp = self.extract_value(data, 'температура двигателя', 'RegistredSensors')
        if temp is not None and temp >= 100:
            alerts.append(f"⚠️ Высокая температура двигателя: {temp}°C")

        lat, lon = data['vehicle'].get('latitude'), data['vehicle'].get('longitude')
        if lat is not None and lon is not None and not is_point_inside_polygon(lat, lon, POLYGON_COORDS):
            alerts.append(f"⚠️ Транспортное средство покинуло зону!\n Координаты - {lat}, {lon}")

        if alerts:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            message = f"🚗 Внимание! {timestamp}\n\n" + "\n".join(alerts)
            try:
                bot.send_message(TARGET_USER_ID, message)
                # bot.send_message(5941825713, message)
            except Exception as e:
                print(f"Failed to send Telegram message: {e}")
