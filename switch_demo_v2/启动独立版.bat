@echo off
chcp 65001 >nul
cd /d "%~dp0"
switch-lab.exe --open
if %errorlevel% neq 0 pause
