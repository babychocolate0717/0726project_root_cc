# app/models.py
from sqlalchemy import Column, Float, String, DateTime, Boolean
from sqlalchemy.sql import func
from .database import Base

class EnergyRaw(Base):
    __tablename__ = "energy_raw"

    timestamp_utc = Column(String, primary_key=True, index=True)
    gpu_model = Column(String)
    gpu_usage_percent = Column(Float)
    gpu_power_watt = Column(Float)
    cpu_power_watt = Column(Float)
    memory_used_mb = Column(Float)
    disk_read_mb_s = Column(Float)
    disk_write_mb_s = Column(Float)
    system_power_watt = Column(Float)
    device_id = Column(String)
    user_id = Column(String)
    agent_version = Column(String)
    os_type = Column(String)
    os_version = Column(String)
    location = Column(String)
    device_fingerprint = Column(String(16), nullable=True)
    risk_level = Column(String(10), nullable=True)  
    similarity_score = Column(Float, nullable=True)

class EnergyCleaned(Base):
    __tablename__ = "energy_cleaned"

    timestamp_utc = Column(String, primary_key=True, index=True)
    gpu_model = Column(String)
    gpu_usage_percent = Column(Float)
    gpu_power_watt = Column(Float)
    cpu_power_watt = Column(Float)
    memory_used_mb = Column(Float)
    disk_read_mb_s = Column(Float)
    disk_write_mb_s = Column(Float)
    system_power_watt = Column(Float)
    device_id = Column(String)
    user_id = Column(String)
    agent_version = Column(String)
    os_type = Column(String)
    os_version = Column(String)
    location = Column(String)
    risk_level = Column(String(10), nullable=True)  
    similarity_score = Column(Float, nullable=True)

# 新增：授權設備表
class AuthorizedDevice(Base):
    __tablename__ = "authorized_devices"
    
    mac_address = Column(String, primary_key=True, index=True)
    device_name = Column(String, nullable=False)
    user_name = Column(String, nullable=False)
    registered_date = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(String, nullable=True)