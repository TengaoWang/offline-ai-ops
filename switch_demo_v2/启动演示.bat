@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -X utf8 server.py --open
  goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -X utf8 server.py --open
  goto :eof
)

echo 未找到 Python 3。请先安装 Python 3.10 或更高版本。
echo 安装后重新双击“启动演示.bat”。
pause
