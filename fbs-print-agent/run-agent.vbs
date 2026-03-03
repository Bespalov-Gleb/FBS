' Запуск FBS Print Agent с CORS для сайта fbs-upakovka.ru (без окна консоли)
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir
WshShell.Environment("Process")("FBS_PRINT_AGENT_ORIGINS") = "https://fbs-upakovka.ru,https://www.fbs-upakovka.ru"
WshShell.Run "fbs-print-agent.exe", 0, False
