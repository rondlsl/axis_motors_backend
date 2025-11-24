from typing import List

from pydantic import BaseModel


class VehicleIdsRequest(BaseModel):
    ids: List[int]


class CommandRequest(BaseModel):
    vehicle_id: int


class RentedCar(BaseModel):
    id: str  
    name: str
    plate_number: str
