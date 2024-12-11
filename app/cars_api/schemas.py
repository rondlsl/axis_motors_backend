from typing import List

from pydantic import BaseModel


class VehicleIdsRequest(BaseModel):
    ids: List[int]


class CommandRequest(BaseModel):
    vehicle_id: int
