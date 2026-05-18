from sqlalchemy import Column, Integer, String, Float
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)


class DevicePairing(Base):
    __tablename__ = "device_pairings"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)
    room_id = Column(String, nullable=False)
    paired_at = Column(Integer, nullable=False)


class EnergyReading(Base):
    __tablename__ = "energy_readings"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String, nullable=False, index=True)
    timestamp = Column(Integer, nullable=False)
    kwh = Column(Float, nullable=False, default=0.0)
    watts = Column(Float, nullable=False, default=0.0)
    volts = Column(Float, nullable=False, default=0.0)
    amps = Column(Float, nullable=False, default=0.0)
    user_id = Column(String, nullable=True)
    source = Column(String, default="live")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    start_time = Column(Integer, nullable=False)
    end_time = Column(Integer, nullable=False)
    duration_s = Column(Integer, nullable=False)
    kwh = Column(Float, nullable=False)
    cost_php = Column(Float, nullable=False)
