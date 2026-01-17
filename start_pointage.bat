@echo off
REM Bot de Pointage - Demarrage automatique avec auto-update
cd /d C:\pointage-bot

:loop
REM Pull les dernières modifications de GitHub
echo [%date% %time%] Verification des mises a jour...
git pull origin main

REM Active l'environnement virtuel et lance une sync
call .venv\Scripts\activate
python run_pointage.py sync

REM Attend 60 secondes avant la prochaine iteration
echo [%date% %time%] Prochaine sync dans 60 secondes...
timeout /t 60 /nobreak >nul

goto loop
