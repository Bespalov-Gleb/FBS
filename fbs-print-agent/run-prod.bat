@echo off
REM Запуск агента для работы с продакшен-сайтом (fbs-upakovka.ru)
REM CORS: без этой переменной браузер заблокирует запросы с сайта
set FBS_PRINT_AGENT_ORIGINS=https://fbs-upakovka.ru,https://www.fbs-upakovka.ru
python main.py
