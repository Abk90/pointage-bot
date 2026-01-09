Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\pointage-bot && .venv\Scripts\python.exe run_pointage.py daemon", 0
Set WshShell = Nothing
