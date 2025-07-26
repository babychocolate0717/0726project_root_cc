# app/auth.py
from fastapi import HTTPException, Header, Depends, Request
from sqlalchemy.orm import Session
import hashlib
import hmac
import os
import logging
from .database import SessionLocal
from .models import AuthorizedDevice
from datetime import datetime

logger = logging.getLogger(__name__)

# 兼容性設置
COMPATIBILITY_MODE = os.getenv("COMPATIBILITY_MODE", "true").lower() == "true"
DEFAULT_ALLOWED_IPS = os.getenv("DEFAULT_ALLOWED_IPS", "").split(",") if os.getenv("DEFAULT_ALLOWED_IPS") else []

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class DeviceAuthenticator:
    def __init__(self, db: Session):
        self.db = db
        self.secret_key = os.getenv("AUTH_SECRET_KEY", "your-default-secret-key")
    
    def is_device_authorized(self, mac_address: str) -> bool:
        """檢查設備是否被授權"""
        if not mac_address:
            return False
            
        mac_address = self._normalize_mac(mac_address)
        
        device = self.db.query(AuthorizedDevice).filter(
            AuthorizedDevice.mac_address == mac_address,
            AuthorizedDevice.is_active == True
        ).first()
        
        if device:
            device.last_seen = datetime.now()
            self.db.commit()
            logger.info(f"Authorized device accessed: {mac_address}")
            return True
        
        logger.warning(f"Unauthorized device attempted access: {mac_address}")
        return False
    
    def verify_certificate(self, mac_address: str, certificate: str) -> bool:
        """驗證設備憑證"""
        if not mac_address or not certificate:
            return False
        
        mac_address = self._normalize_mac(mac_address)
        expected_cert = hmac.new(
            self.secret_key.encode(), 
            mac_address.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        return certificate == expected_cert
    
    def _normalize_mac(self, mac_address: str) -> str:
        """標準化 MAC 地址格式"""
        return mac_address.upper().replace('-', ':')

# 兼容性認證依賴
async def verify_device_auth_compatible(
    request: Request,
    mac_address: str = Header(None, alias="MAC-Address"),
    device_certificate: str = Header(None, alias="Device-Certificate"),
    db: Session = Depends(get_db)
):
    """兼容舊版 Agent 的認證中間件"""
    
    # 模式 1：新版 Agent (有完整認證 Headers)
    if mac_address and device_certificate:
        logger.info("Using new authentication method")
        authenticator = DeviceAuthenticator(db)
        
        if not authenticator.is_device_authorized(mac_address):
            raise HTTPException(status_code=403, detail="Device not authorized")
        
        if not authenticator.verify_certificate(mac_address, device_certificate):
            raise HTTPException(status_code=401, detail="Invalid device certificate")
        
        return {"mac_address": mac_address, "authenticated": True, "method": "full_auth"}
    
    # 模式 2：兼容模式 (舊版 Agent)
    elif COMPATIBILITY_MODE:
        logger.warning("Using compatibility mode for legacy agent")
        client_ip = request.client.host
        
        # 檢查 IP 白名單 (臨時方案)
        if DEFAULT_ALLOWED_IPS and client_ip in DEFAULT_ALLOWED_IPS:
            logger.info(f"Legacy agent allowed by IP: {client_ip}")
            return {"mac_address": f"legacy-{client_ip}", "authenticated": True, "method": "ip_whitelist"}
        
        # 預設允許 (兼容模式)
        logger.info(f"Legacy agent allowed in compatibility mode: {client_ip}")
        return {"mac_address": f"legacy-{client_ip}", "authenticated": True, "method": "legacy_mode"}
    
    # 模式 3：嚴格模式 (拒絕舊版)
    else:
        raise HTTPException(
            status_code=401, 
            detail="Missing authentication headers. Please upgrade your agent."
        )