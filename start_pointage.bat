@echo off
REM Bot de Pointage - Demarrage automatique
cd /d C:\pointage-bot
call .venv\Scripts\activate
python run_pointage.py daemon
pause
