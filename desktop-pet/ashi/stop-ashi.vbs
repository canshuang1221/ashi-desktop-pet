' ashi stopper
' NOTE: keep this file pure ASCII (wscript reads .vbs as ANSI/GBK).
Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c taskkill /IM ashi.exe /F >nul 2>&1", 0, True
WScript.Quit
