from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from . import models, schemas
from .database import SessionLocal, engine, Base
from .auth import verify_device_auth_compatible, get_db, DeviceAuthenticator
from .utils.mac_manager import MACManager
import requests
import logging
from datetime import datetime
from typing import List
from sqlalchemy import text, func, distinct

app = FastAPI(title="Energy Data Ingestion API", version="1.2.0")

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
        "version": "1.2.0",
        "features": ["MAC Authentication", "Device Fingerprint", "Device Management", "Health Monitoring"]
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
    """接收能耗資料並進行處理（使用指紋認證，不強制白名單）"""
    logger.info(f"Received data from device: {auth['mac_address']} (method: {auth['method']})")
    
    try:
        # 設備指紋檢查（主要認證方式）
        authenticator = DeviceAuthenticator(db)
        fingerprint_result = authenticator.check_device_fingerprint(data.dict())
        
        # 記錄指紋檢查結果
        risk_level = fingerprint_result["risk_level"]
        is_whitelisted = auth.get('whitelisted', False)
        
        logger.info(f"Device {data.device_id} fingerprint: {risk_level} - {fingerprint_result['message']} (whitelisted: {is_whitelisted})")
        
        # 根據指紋風險等級決定處理方式
        if risk_level == "high" and not is_whitelisted:
            logger.warning(f"⚠️ High risk device detected but allowed: {data.device_id}")
        elif risk_level == "high" and is_whitelisted:
            logger.info(f"✅ High risk device allowed due to whitelist: {data.device_id}")
        
        # 寫入 raw 資料（加入指紋資訊）
        raw_data = data.dict()
        raw_data['device_fingerprint'] = fingerprint_result.get('fingerprint', '')
        raw_data['risk_level'] = fingerprint_result['risk_level']
        raw_data['similarity_score'] = fingerprint_result.get('similarity_score', 0.0)
        
        raw_record = models.EnergyRaw(**raw_data)
        db.add(raw_record)

        # 呼叫 cleaning-api
        try:
            response = requests.post("http://cleaner:8100/clean", json=data.dict(), timeout=10)
            response.raise_for_status()
            cleaned_data = response.json()["cleaned_data"]
            
            # 清洗後的資料也加入指紋資訊
            cleaned_data['device_fingerprint'] = fingerprint_result.get('fingerprint', '')
            cleaned_data['risk_level'] = fingerprint_result['risk_level']
            
            cleaned_record = models.EnergyCleaned(**cleaned_data)
            db.add(cleaned_record)
            
            db.commit()
            logger.info(f"✅ Successfully processed data from {data.device_id}")
            
            return {
                "status": "success", 
                "device": data.device_id, 
                "auth_method": auth['method'],
                "fingerprint_check": {
                    "risk_level": fingerprint_result['risk_level'],
                    "similarity_score": fingerprint_result.get('similarity_score', 0.0),
                    "message": fingerprint_result['message'],
                    "whitelisted": is_whitelisted
                }
            }
            
        except Exception as e:
            # 即使清洗失敗，也要儲存原始資料
            db.commit()
            logger.warning(f"Cleaning failed for {data.device_id}: {str(e)}")
            return {
                "status": "partial_success", 
                "device": data.device_id, 
                "reason": str(e), 
                "auth_method": auth['method'],
                "fingerprint_check": fingerprint_result
            }
            
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to process data from {data.device_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

# ==========================================================================
# 管理端點 - 安全存取版本
# ==========================================================================

@app.get("/admin/dashboard")
async def get_dashboard(db: Session = Depends(get_db)):
    """取得後台總覽資訊"""
    try:
        # 基本統計
        total_records = db.query(models.EnergyRaw).count()
        unique_devices = db.query(func.count(distinct(models.EnergyRaw.device_id))).scalar()
        
        # 今日統計
        today = datetime.now().date()
        today_records = db.query(models.EnergyRaw).filter(
            models.EnergyRaw.timestamp_utc.like(f"{today}%")
        ).count()
        
        # 風險等級統計（安全檢查）
        try:
            risk_stats = db.query(
                models.EnergyRaw.risk_level,
                func.count(models.EnergyRaw.risk_level)
            ).filter(
                models.EnergyRaw.risk_level.isnot(None)
            ).group_by(models.EnergyRaw.risk_level).all()
            
            risk_summary = {level: count for level, count in risk_stats}
        except:
            risk_summary = {}
        
        # 白名單設備統計
        try:
            whitelisted_devices = db.query(models.AuthorizedDevice).filter(
                models.AuthorizedDevice.is_active == True
            ).count()
        except:
            whitelisted_devices = 0
        
        return {
            "total_records": total_records,
            "unique_devices": unique_devices,
            "records_today": today_records,
            "risk_summary": risk_summary,
            "whitelisted_devices": whitelisted_devices,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Dashboard query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Dashboard error: {str(e)}")

@app.get("/admin/device-ids")
async def get_device_ids(db: Session = Depends(get_db)):
    """取得所有設備ID列表"""
    try:
        # 取得所有不同的設備ID及其最新記錄
        device_ids = db.query(distinct(models.EnergyRaw.device_id)).all()
        
        id_list = []
        for row in device_ids:
            device_id = row[0]
            
            # 取得該設備的最新記錄
            latest_record = db.query(models.EnergyRaw).filter(
                models.EnergyRaw.device_id == device_id
            ).order_by(models.EnergyRaw.timestamp_utc.desc()).first()
            
            if latest_record:
                id_list.append({
                    "device_id": device_id,
                    "user_id": getattr(latest_record, 'user_id', 'Unknown'),
                    "last_seen": latest_record.timestamp_utc,
                    "risk_level": getattr(latest_record, 'risk_level', 'unknown'),
                    "gpu_model": getattr(latest_record, 'gpu_model', 'Unknown'),
                    "os_type": getattr(latest_record, 'os_type', 'Unknown'),
                    "similarity_score": getattr(latest_record, 'similarity_score', 0.0)
                })
        
        return {
            "device_ids": id_list,
            "total_count": len(id_list)
        }
    except Exception as e:
        logger.error(f"Device IDs query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

@app.get("/admin/devices-simple")
async def get_devices_simple(db: Session = Depends(get_db)):
    """取得所有設備的簡化列表"""
    try:
        # 取得最近的記錄並去重
        devices = db.query(models.EnergyRaw).order_by(
            models.EnergyRaw.timestamp_utc.desc()
        ).limit(200).all()
        
        # 去重並取得每個設備的最新記錄
        device_dict = {}
        for device in devices:
            if device.device_id not in device_dict:
                device_dict[device.device_id] = device
        
        device_list = []
        for device_id, device in device_dict.items():
            device_info = {
                "device_id": device.device_id,
                "user_id": getattr(device, 'user_id', 'Unknown'),
                "gpu_model": getattr(device, 'gpu_model', 'Unknown'),
                "os_type": getattr(device, 'os_type', 'Unknown'),
                "os_version": getattr(device, 'os_version', 'Unknown'),
                "agent_version": getattr(device, 'agent_version', 'Unknown'),
                "location": getattr(device, 'location', 'Unknown'),
                "last_seen": device.timestamp_utc,
                "risk_level": getattr(device, 'risk_level', 'unknown'),
                "device_fingerprint": getattr(device, 'device_fingerprint', 'N/A'),
                "similarity_score": getattr(device, 'similarity_score', 0.0),
                "cpu_power": getattr(device, 'cpu_power_watt', 0.0),
                "gpu_power": getattr(device, 'gpu_power_watt', 0.0),
                "system_power": getattr(device, 'system_power_watt', 0.0)
            }
            device_list.append(device_info)
        
        return {
            "devices": device_list,
            "total_count": len(device_list)
        }
    except Exception as e:
        logger.error(f"Devices query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

@app.get("/admin/device/{device_id}")
async def get_device_simple_details(device_id: str, db: Session = Depends(get_db)):
    """取得特定設備的詳細記錄（簡化版）"""
    try:
        # 取得設備最近10筆記錄
        records = db.query(models.EnergyRaw).filter(
            models.EnergyRaw.device_id == device_id
        ).order_by(models.EnergyRaw.timestamp_utc.desc()).limit(10).all()
        
        if not records:
            raise HTTPException(status_code=404, detail="Device not found")
        
        # 統計資訊
        total_records = db.query(models.EnergyRaw).filter(
            models.EnergyRaw.device_id == device_id
        ).count()
        
        latest_record = records[0]
        
        return {
            "device_info": {
                "device_id": device_id,
                "user_id": getattr(latest_record, 'user_id', 'Unknown'),
                "gpu_model": getattr(latest_record, 'gpu_model', 'Unknown'),
                "os_type": getattr(latest_record, 'os_type', 'Unknown'),
                "os_version": getattr(latest_record, 'os_version', 'Unknown'),
                "agent_version": getattr(latest_record, 'agent_version', 'Unknown'),
                "location": getattr(latest_record, 'location', 'Unknown'),
                "first_seen": records[-1].timestamp_utc,
                "last_seen": latest_record.timestamp_utc
            },
            "statistics": {
                "total_records": total_records
            },
            "fingerprint_history": [
                {
                    "timestamp": r.timestamp_utc,
                    "fingerprint": getattr(r, 'device_fingerprint', 'N/A'),
                    "risk_level": getattr(r, 'risk_level', 'unknown'),
                    "similarity_score": getattr(r, 'similarity_score', 0.0)
                } for r in records if getattr(r, 'device_fingerprint', None)
            ],
            "recent_records": [
                {
                    "timestamp": r.timestamp_utc,
                    "cpu_power": getattr(r, 'cpu_power_watt', 0.0),
                    "gpu_power": getattr(r, 'gpu_power_watt', 0.0),
                    "system_power": getattr(r, 'system_power_watt', 0.0),
                    "risk_level": getattr(r, 'risk_level', 'unknown'),
                    "similarity_score": getattr(r, 'similarity_score', 0.0)
                } for r in records
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Device details query failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

@app.get("/admin/high-risk")
async def get_high_risk_simple(db: Session = Depends(get_db)):
    """取得高風險設備列表（簡化版）"""
    try:
        high_risk_devices = db.query(models.EnergyRaw).filter(
            models.EnergyRaw.risk_level == "high"
        ).order_by(models.EnergyRaw.timestamp_utc.desc()).limit(20).all()
        
        devices = []
        for device in high_risk_devices:
            devices.append({
                "device_id": device.device_id,
                "user_id": getattr(device, 'user_id', 'Unknown'),
                "timestamp": device.timestamp_utc,
                "risk_level": getattr(device, 'risk_level', 'unknown'),
                "similarity_score": getattr(device, 'similarity_score', 0.0),
                "device_fingerprint": getattr(device, 'device_fingerprint', 'N/A'),
                "gpu_model": getattr(device, 'gpu_model', 'Unknown')
            })
        
        return {
            "high_risk_devices": devices,
            "count": len(devices)
        }
    except Exception as e:
        logger.error(f"High risk devices query failed: {str(e)}")
        return {
            "high_risk_devices": [],
            "count": 0,
            "error": str(e)
        }

# ==========================================================================
# 原有的設備管理端點（白名單相關）
# ==========================================================================

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

# ==========================================================================
# 系統監控端點
# ==========================================================================

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
        
        try:
            active_devices = db.query(models.AuthorizedDevice).filter(
                models.AuthorizedDevice.is_active == True
            ).count()
        except:
            active_devices = 0
        
        # 異常設備統計
        try:
            high_risk_count = db.query(models.EnergyRaw).filter(
                models.EnergyRaw.timestamp_utc.like(f"{today}%"),
                models.EnergyRaw.risk_level == "high"
            ).count()
            
            medium_risk_count = db.query(models.EnergyRaw).filter(
                models.EnergyRaw.timestamp_utc.like(f"{today}%"),
                models.EnergyRaw.risk_level == "medium"
            ).count()
        except:
            high_risk_count = 0
            medium_risk_count = 0
        
        return {
            "records_today": {
                "raw": raw_count,
                "cleaned": cleaned_count,
                "success_rate": f"{(cleaned_count/raw_count*100):.1f}%" if raw_count > 0 else "0%"
            },
            "active_devices": active_devices,
            "security_status": {
                "high_risk_devices": high_risk_count,
                "medium_risk_devices": medium_risk_count,
                "total_anomalies": high_risk_count + medium_risk_count
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Metrics collection failed: {str(e)}")
        return {"error": "Unable to collect metrics"}