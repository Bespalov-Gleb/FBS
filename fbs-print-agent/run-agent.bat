@echo off
REM Запуск FBS Print Agent с привязкой к сайту fbs-upakovka.ru
REM Без этой переменной браузер заблокирует печать с сайта (CORS)
set FBS_PRINT_AGENT_ORIGINS=https://fbs-upakovka.ru,https://www.fbs-upakovka.ru
cd /d "%~dp0"
start "" "fbs-print-agent.exe"
