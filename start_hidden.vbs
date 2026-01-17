Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\pointage-bot && start_pointage.bat", 0
Set WshShell = Nothing
