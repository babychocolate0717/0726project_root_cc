# app/main.py
from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from . import models, schemas
from .database import SessionLocal, engine, Base
from .auth import verify_device_auth_compatible, get_db
from .utils.mac_manager import MACManager
import requests
import logging
from datetime import datetime
from typing import List
from sqlalchemy import text

app = FastAPI(title="Energy Data Ingestion API", version="1.1.0")

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 建立所有資料表
logger.info("開始建立資料表...")
Base.metadata.create_all(bind=engine)
logger.info("資料表建立完成")

@app.get("/")
async def root():
    return {
        "message": "Energy Data Ingestion API", 
        "version": "1.1.0",
        "features": ["MAC Authentication", "Device Management", "Health Monitoring"]
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """健康檢查端點"""
    try:
        # 檢查資料庫連接
        db.execute(text("SELECT 1"))
        
        # 檢查清洗服務
        try:
            response = requests.get("http://cleaner:8100/health", timeout=5)
            cleaner_healthy = response.status_code == 200
        except:
            cleaner_healthy = False
        
        return {
            "status": "healthy" if cleaner_healthy else "partial",
            "database": "connected",
            "cleaner_service": "connected" if cleaner_healthy else "disconnected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.post("/ingest")
def ingest(
    request: Request,
    data: schemas.EnergyData, 
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_device_auth_compatible)
):
    """接收能耗資料並進行處理"""
    logger.info(f"Received data from device: {auth['mac_address']} (method: {auth['method']})")
    
    try:
        # 1️⃣ 寫入 raw 資料
        raw_record = models.EnergyRaw(**data.dict())
        db.add(raw_record)

        # 2️⃣ 呼叫 cleaning-api
        try:
            response = requests.post("http://cleaner:8100/clean", json=data.dict(), timeout=10)
            response.raise_for_status()
            cleaned_data = response.json()["cleaned_data"]
            cleaned_record = models.EnergyCleaned(**cleaned_data)
            db.add(cleaned_record)
            
            db.commit()
            logger.info(f"Successfully processed data from {data.device_id}")
            return {"status": "success", "device": data.device_id, "auth_method": auth['method']}
            
        except Exception as e:
            # 即使清洗失敗，也要儲存原始資料
            db.commit()
            logger.warning(f"Cleaning failed for {data.device_id}: {str(e)}")
            return {"status": "partial_success", "device": data.device_id, "reason": str(e), "auth_method": auth['method']}
            
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to process data from {data.device_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

# 設備管理端點
@app.get("/admin/devices", response_model=List[schemas.DeviceResponse])
async def list_devices(db: Session = Depends(get_db)):
    """列出所有授權設備"""
    manager = MACManager(db)
    return manager.list_devices()

@app.post("/admin/devices")
async def add_device(device_data: schemas.DeviceCreate, db: Session = Depends(get_db)):
    """新增設備到白名單"""
    manager = MACManager(db)
    success = manager.add_device(
        device_data.mac_address,
        device_data.device_name,
        device_data.user_name,
        device_data.notes
    )
    
    if success:
        return {"status": "success", "message": "Device added to whitelist"}
    else:
        raise HTTPException(status_code=400, detail="Failed to add device or device already exists")

@app.delete("/admin/devices/{mac_address}")
async def remove_device(mac_address: str, db: Session = Depends(get_db)):
    """從白名單移除設備"""
    manager = MACManager(db)
    success = manager.remove_device(mac_address)
    
    if success:
        return {"status": "success", "message": "Device removed from whitelist"}
    else:
        raise HTTPException(status_code=404, detail="Device not found")

@app.get("/admin/devices/{mac_address}", response_model=schemas.DeviceResponse)
async def get_device_info(mac_address: str, db: Session = Depends(get_db)):
    """取得設備詳細資訊"""
    manager = MACManager(db)
    device = manager.get_device(mac_address)
    
    if device:
        return device
    else:
        raise HTTPException(status_code=404, detail="Device not found")

# 監控端點
@app.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)):
    """取得系統指標"""
    try:
        today = datetime.now().date()
        
        raw_count = db.query(models.EnergyRaw).filter(
            models.EnergyRaw.timestamp_utc.like(f"{today}%")
        ).count()
        
        cleaned_count = db.query(models.EnergyCleaned).filter(
            models.EnergyCleaned.timestamp_utc.like(f"{today}%")
        ).count()
        
        active_devices = db.query(models.AuthorizedDevice).filter(
            models.AuthorizedDevice.is_active == True
        ).count()
        
        return {
            "records_today": {
                "raw": raw_count,
                "cleaned": cleaned_count,
                "success_rate": f"{(cleaned_count/raw_count*100):.1f}%" if raw_count > 0 else "0%"
            },
            "active_devices": active_devices,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Metrics collection failed: {str(e)}")
        return {"error": "Unable to collect metrics"}