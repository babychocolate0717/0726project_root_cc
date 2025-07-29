# agent_with_auth.py
import psutil
import platform
import uuid
import getpass
import time
import json
import csv
import os
import requests
import hashlib
import hmac
from datetime import datetime, timezone, time as dtime
import subprocess
from pynput import mouse, keyboard
import threading
import socket

# ---------- 配置設定 ----------
API_BASE_URL = "http://localhost:8000"  # 您的 ingestion-api 地址
AUTH_SECRET_KEY = "NTCUST-ENERGY-MONITOR"  # 🆕 更新與 API 相同的密鑰
FALLBACK_TO_CSV = True  # 如果 API 不可用，是否儲存到 CSV

# ---------- 上課節次時間設定 ----------
class_periods = [
    ("08:10", "09:00"), ("09:10", "10:00"),
    ("10:10", "11:00"), ("11:10", "12:00"),
    ("13:25", "14:15"), ("14:20", "15:10"),
    ("15:20", "16:10"), ("16:15", "17:05")
]

def is_class_time():
    now = datetime.now().time()
    for start_str, end_str in class_periods:
        start = dtime.fromisoformat(start_str)
        end = dtime.fromisoformat(end_str)
        if start <= now <= end:
            return True
    return False

# ---------- MAC 地址和認證功能 ----------
def get_mac_address():
    """取得設備 MAC 地址"""
    try:
        # 方法 1: 使用 uuid.getnode()
        mac = uuid.getnode()
        mac_str = ':'.join(['{:02x}'.format((mac >> elements) & 0xff) 
                           for elements in range(0,2*6,2)][::-1])
        return mac_str.upper()
    except:
        try:
            # 方法 2: 使用網路介面
            import netifaces
            interfaces = netifaces.interfaces()
            for interface in interfaces:
                if interface != 'lo':  # 排除本地回環
                    addrs = netifaces.ifaddresses(interface)
                    if netifaces.AF_LINK in addrs:
                        mac = addrs[netifaces.AF_LINK][0]['addr']
                        return mac.upper().replace('-', ':')
        except:
            pass
        
        # 方法 3: 系統指令 (備用)
        try:
            if platform.system() == "Windows":
                result = subprocess.run(['getmac'], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if '-' in line and len(line.split('-')) == 6:
                        return line.replace('-', ':').upper().strip()
            else:  # Linux/macOS
                result = subprocess.run(['ifconfig'], capture_output=True, text=True)
                # 簡化版解析，實際可能需要更複雜的正則表達式
                pass
        except:
            pass
    
    return "00:00:00:00:00:00"  # 預設值

def generate_device_certificate(mac_address, secret_key):
    """生成設備憑證"""
    return hmac.new(
        secret_key.encode(), 
        mac_address.encode(), 
        hashlib.sha256
    ).hexdigest()

def get_auth_headers():
    """取得認證 Headers"""
    mac_address = get_mac_address()
    certificate = generate_device_certificate(mac_address, AUTH_SECRET_KEY)
    
    return {
        "Content-Type": "application/json",
        "MAC-Address": mac_address,
        "Device-Certificate": certificate
    }

# ---------- 🆕 增強硬體資訊收集（用於指紋生成）----------
def get_enhanced_system_info():
    """收集更詳細的系統資訊用於設備指紋"""
    try:
        system_info = {
            "cpu_model": platform.processor() or "Unknown",
            "cpu_count": psutil.cpu_count(),
            "total_memory": psutil.virtual_memory().total,
            "disk_partitions": len(psutil.disk_partitions()),
            "network_interfaces": len(psutil.net_if_addrs()),
            "platform_machine": platform.machine(),
            "platform_architecture": platform.architecture()[0]
        }
        return system_info
    except:
        return {}

# ---------- 硬體數據擷取 (保持原有邏輯) ----------
def get_gpu_model():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=gpu_name', '--format=csv,noheader'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.stderr:
            return "Unknown"
        return result.stdout.decode('utf-8').strip()
    except:
        return "Unknown"

def get_gpu_usage():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.stderr:
            return 0
        usage = result.stdout.decode('utf-8').strip()
        return float(usage) if usage else 0
    except:
        return 0

def get_gpu_power_watt():
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=power.draw', '--format=csv,noheader,nounits'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.stderr:
            return 0
        power = result.stdout.decode('utf-8').strip()
        return float(power) if power else 0
    except:
        return 0

def get_cpu_power():
    return round(psutil.cpu_percent(interval=1) * 0.5, 2)

def get_memory_usage():
    memory = psutil.virtual_memory()
    return memory.used / (1024 * 1024)

def get_disk_read_write_rate(interval=1):
    before = psutil.disk_io_counters()
    time.sleep(interval)
    after = psutil.disk_io_counters()

    read_rate = (after.read_bytes - before.read_bytes) / (1024 * 1024) / interval
    write_rate = (after.write_bytes - before.write_bytes) / (1024 * 1024) / interval
    return round(read_rate, 2), round(write_rate, 2)

def get_system_power(cpu, gpu, memory):
    return cpu + gpu + (memory * 0.1)

def get_timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def get_device_info():
    return (
        str(uuid.getnode()),
        getpass.getuser(),
        "v1.2.0",  # 🆕 升級版本號支援指紋功能
        platform.system(),
        platform.version(),
        "Taipei, Taiwan"
    )

# ---------- 資料傳送 (新增 API 功能) ----------
def send_to_api(data):
    """發送資料到 ingestion-api"""
    try:
        headers = get_auth_headers()
        
        # 轉換資料格式以符合 API schema
        api_data = {
            "timestamp_utc": data["timestamp"],
            "gpu_model": data["gpu_model"],
            "gpu_usage_percent": data["gpu_usage"],
            "gpu_power_watt": data["gpu"],
            "cpu_power_watt": data["cpu"],
            "memory_used_mb": data["memory"],
            "disk_read_mb_s": data["disk_read"],
            "disk_write_mb_s": data["disk_write"],
            "system_power_watt": data["system_power"],
            "device_id": data["device_id"],
            "user_id": data["user_id"],
            "agent_version": data["agent_version"],
            "os_type": data["os_type"],
            "os_version": data["os_version"],
            "location": data["location"]
        }
        
        response = requests.post(
            f"{API_BASE_URL}/ingest",
            json=api_data,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # 🆕 顯示指紋檢查結果
            if "fingerprint_check" in result:
                fp_result = result["fingerprint_check"]
                risk_level = fp_result.get("risk_level", "unknown")
                message = fp_result.get("message", "")
                similarity = fp_result.get("similarity_score", 0)
                
                if risk_level == "high":
                    print(f"⚠️ 高風險設備警告: {message} (相似度: {similarity:.2f})")
                elif risk_level == "medium":
                    print(f"⚡ 中風險提醒: {message} (相似度: {similarity:.2f})")
                else:
                    print(f"✅ 設備正常: {message} (相似度: {similarity:.2f})")
            
            print(f"✅ 資料已成功傳送到 API: {result.get('status', 'unknown')}")
            return True
            
        elif response.status_code == 401:
            print(f"❌ 認證失敗: {response.json().get('detail', 'Unknown auth error')}")
            return False
        elif response.status_code == 403:
            print(f"❌ 設備未授權: {response.json().get('detail', 'Device not authorized')}")
            print(f"   您的 MAC 地址: {get_mac_address()}")
            print(f"   請聯繫管理員將此設備加入白名單")
            return False
        else:
            print(f"❌ API 回應錯誤: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ 無法連接到 API: {API_BASE_URL}")
        return False
    except requests.exceptions.Timeout:
        print("❌ API 請求逾時")
        return False
    except Exception as e:
        print(f"❌ 發送資料失敗: {str(e)}")
        return False

# ---------- CSV 備援儲存 (保持原有邏輯) ----------
data_buffer = []
file_count = 0
output_dir = "agent_logs"
os.makedirs(output_dir, exist_ok=True)

def save_to_csv(row):
    global data_buffer, file_count
    data_buffer.append(row)
    if len(data_buffer) >= 50:
        filename = os.path.join(output_dir, f"agent_data_{file_count}.csv")
        with open(filename, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            writer.writeheader()
            writer.writerows(data_buffer)
        print(f"💾 CSV 備份已儲存：{filename}")
        data_buffer = []
        file_count += 1

# ---------- 資料處理和儲存 ----------
def process_and_send_data():
    """處理和發送資料"""
    device_id, user_id, agent_version, os_type, os_version, location = get_device_info()
    timestamp = get_timestamp()

    gpu_model = get_gpu_model()
    gpu_usage = get_gpu_usage()
    gpu_power = get_gpu_power_watt()
    cpu_power = get_cpu_power()
    memory_used = get_memory_usage()
    disk_read, disk_write = get_disk_read_write_rate(interval=1)
    system_power = get_system_power(cpu_power, gpu_power, memory_used)

    # 🆕 收集增強的系統資訊（指紋相關）
    enhanced_info = get_enhanced_system_info()

    data = {
        "timestamp": timestamp,
        "cpu": cpu_power,
        "gpu": gpu_power,
        "memory": memory_used,
        "disk_read": disk_read,
        "disk_write": disk_write,
        "gpu_usage": gpu_usage,
        "gpu_model": gpu_model,
        "system_power": system_power,
        "device_id": device_id,
        "user_id": user_id,
        "agent_version": agent_version,
        "os_type": os_type,
        "os_version": os_version,
        "location": location,
        # 🆕 新增增強系統資訊
        **enhanced_info
    }

    print("\n========== 資料輸出 ==========")
    for k, v in data.items():
        print(f"{k}: {v}")
    
    # 嘗試發送到 API
    api_success = send_to_api(data)
    
    # 如果 API 失敗且啟用備援，則儲存到 CSV
    if not api_success and FALLBACK_TO_CSV:
        print("🔄 API 發送失敗，使用 CSV 備援儲存")
        save_to_csv(data)
    
    return api_success

# ---------- 差異判斷 (保持原有邏輯) ----------
previous_data = {"cpu": 0, "gpu": 0, "memory": 0, "disk_read": 0, "disk_write": 0}
CHANGE_THRESHOLD = 5

def has_significant_change(new, old):
    changes = [k for k in new if abs(new[k] - old[k]) > CHANGE_THRESHOLD]
    if changes:
        print(f"📊 資料變動超過閾值：{', '.join(changes)}")
        return True
    return False

# ---------- 使用者操作偵測 (保持原有邏輯) ----------
user_active = False

def on_event(x):
    global user_active
    user_active = True

def monitor_input():
    try:
        with mouse.Listener(on_click=on_event), keyboard.Listener(on_press=on_event):
            while True:
                time.sleep(1)
    except Exception as e:
        print(f"⚠️ 輸入監控啟動失敗: {e}")

threading.Thread(target=monitor_input, daemon=True).start()

# ---------- 初始化和健康檢查 ----------
def check_api_connection():
    """檢查 API 連接並驗證設備註冊狀態"""
    try:
        # 檢查 API 健康狀態
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API 服務運行正常")
        else:
            print(f"⚠️ API 健康檢查異常: {response.status_code}")
    except:
        print(f"❌ 無法連接到 API: {API_BASE_URL}")
        if FALLBACK_TO_CSV:
            print("🔄 將使用 CSV 備援模式")
        return False
    
    # 檢查設備是否已註冊
    mac_address = get_mac_address()
    print(f"🔍 設備 MAC 地址: {mac_address}")
    print(f"🔧 設備指紋功能: 已啟用")  # 🆕 新增指紋狀態顯示
    
    try:
        headers = get_auth_headers()
        response = requests.get(f"{API_BASE_URL}/admin/devices/{mac_address}", headers=headers, timeout=5)
        
        if response.status_code == 200:
            device_info = response.json()
            print(f"✅ 設備已註冊: {device_info['device_name']}")
            return True
        elif response.status_code == 404:
            print("⚠️ 設備尚未註冊到白名單，但指紋功能仍可運作")
            return True  # 🆕 指紋模式下無需白名單也可運作
        else:
            print(f"❌ 檢查設備註冊狀態失敗: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 檢查設備註冊失敗: {e}")
        return False

# ---------- 主迴圈 ----------
def main():
    global user_active, previous_data 
    
    print("🚀 Agent 啟動中...")
    print(f"📡 API 地址: {API_BASE_URL}")
    print(f"🔐 MAC 地址: {get_mac_address()}")
    print(f"🆕 版本: v1.2.0 (支援設備指紋)")  # 🆕 版本資訊
    
    # 初始化檢查
    api_available = check_api_connection()
    
    if not api_available and not FALLBACK_TO_CSV:
        print("❌ API 不可用且未啟用 CSV 備援，程式結束")
        return
    
    print("⏰ 開始監控...")
    
    while True:
        try:
            in_class = is_class_time()
            should_grab = False

            if in_class:
                should_grab = True
                print("📚 上課時間，持續監控")
            elif user_active:
                should_grab = True
                print("👆 偵測到使用者活動")
                user_active = False

            if should_grab:
                cpu_power = get_cpu_power()
                gpu_power = get_gpu_power_watt()
                memory_used = get_memory_usage()
                disk_read, disk_write = get_disk_read_write_rate(interval=1)

                new_data = {
                    "cpu": cpu_power,
                    "gpu": gpu_power,
                    "memory": memory_used,
                    "disk_read": disk_read,
                    "disk_write": disk_write,
                }

                if has_significant_change(new_data, previous_data):
                    success = process_and_send_data()
                    previous_data = new_data

            time.sleep(60)
            
        except KeyboardInterrupt:
            print("\n👋 Agent 停止運行")
            break
        except Exception as e:
            print(f"❌ 運行時錯誤: {e}")
            time.sleep(60)  # 等待後重試

# ---------- 啟動 ----------
if __name__ == "__main__":
    main()