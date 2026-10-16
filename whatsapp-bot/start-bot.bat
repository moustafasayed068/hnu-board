@echo off
title HNU WhatsApp Bot
chcp 65001 >nul
cd /d "%~dp0"

rem Restart the bot automatically if it stops (no internet at startup, crash...).
:loop
echo [%date% %time%] Starting bot...
call npm start
echo [%date% %time%] Bot stopped. Restarting in 15 seconds (close this window to stop it)...
timeout /t 15 /nobreak >nul
goto loop
