' ashi launcher: kill old instance, then start fresh
' NOTE: keep this file pure ASCII. wscript reads .vbs as ANSI/GBK by
' default, so UTF-8 Chinese comments can break parsing on some machines.
Set sh = CreateObject("Shell.Application")
Set ws = CreateObject("WScript.Shell")
ws.Run "cmd /c taskkill /IM ashi.exe /F >nul 2>&1", 0, True
WScript.Sleep 1200
sh.ShellExecute "E:\WorkBuddy\Git\desktop-pet\ashi\dist\ashi.exe", "", "", "open", 1
WScript.Quit
