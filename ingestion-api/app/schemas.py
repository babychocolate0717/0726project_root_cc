# app/schemas.py
from pydantic import BaseModel, validator
from datetime import datetime
from typing import Optional

class EnergyData(BaseModel):
    timestamp_utc: str
    gpu_model: str
    gpu_usage_percent: float
    gpu_power_watt: float
    cpu_power_watt: float
    memory_used_mb: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    system_power_watt: float
    device_id: str
    user_id: str
    agent_version: str
    os_type: str
    os_version: str
    location: str
    
    # 資料驗證
    @validator('gpu_usage_percent')
    def validate_gpu_usage(cls, v):
        if not 0 <= v <= 100:
            raise ValueError('GPU usage must be between 0 and 100')
        return v
    
    @validator('gpu_power_watt', 'cpu_power_watt', 'system_power_watt')
    def validate_power(cls, v):
        if not 0 <= v <= 1000:
            raise ValueError('Power consumption must be between 0 and 1000W')
        return v
    
    @validator('memory_used_mb')
    def validate_memory(cls, v):
        if not 0 <= v <= 128000:
            raise ValueError('Memory usage must be between 0 and 128GB')
        return v

# 新增：設備管理 schemas
class DeviceCreate(BaseModel):
    mac_address: str
    device_name: str
    user_name: str
    notes: Optional[str] = None

class DeviceResponse(BaseModel):
    mac_address: str
    device_name: str
    user_name: str
    registered_date: datetime
    last_seen: Optional[datetime]
    is_active: bool
    notes: Optional[str]
    
    class Config:
        from_attributes = True