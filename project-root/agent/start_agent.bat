@echo off
echo [%date% %time%] Starting Energy Monitor Agent...
cd /d "C:\Users\alisa\OneDrive\Desktop\cc\project-root\agent"
if not exist "logs" mkdir logs
echo [%date% %time%] Agent startup initiated >> logs\startup.log
"C:\Users\alisa\AppData\Local\Programs\Python\Python310\python.exe" -u "agent_with_auth.py" >> logs\agent_output.log 2>> logs\agent_error.log
echo [%date% %time%] Agent process ended >> logs\startup.log
