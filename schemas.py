from pydantic import BaseModel
from typing import Optional


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class PairRequest(BaseModel):
    room_id: str


class EnergyPost(BaseModel):
    room_id: str
    timestamp: int
    kwh: float
    watts: float
    volts: float
    amps: float
    user_id: Optional[str] = None
    source: Optional[str] = "live"


class SessionPost(BaseModel):
    room_id: str
    user_id: str
    start_time: int
    end_time: int
    duration_s: int
    kwh: float
    cost_php: float


class LiveReading(BaseModel):
    room_id: str
    timestamp: int
    kwh: float
    watts: float
    volts: float
    amps: float
    user_id: Optional[str] = None


class AdminRequest(BaseModel):
    password: str
    clear_users: bool = False
