@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
set "NEEDS_INSTALL=0"

if not exist "%PYTHON_BIN%" goto :create_venv

rem 只判断文件存在会放过损坏的虚拟环境（例如从机器复制而来、pyvenv.cfg 指向不存在的解释器），
rem 所以必须先真正执行一次解释器；执行失败就删除并重建。
"%PYTHON_BIN%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :rebuild_venv
goto :check_deps

:rebuild_venv
echo [start] .venv 解释器不可用，正在重建...
rmdir /s /q ".venv"

:create_venv
echo [start] 正在创建 .venv...
python -m venv .venv
if errorlevel 1 goto :fail_venv
set "NEEDS_INSTALL=1"

:check_deps
"%PYTHON_BIN%" -c "import apscheduler, cryptography, fastapi, loguru, urllib3, uvicorn" >nul 2>&1
if errorlevel 1 set "NEEDS_INSTALL=1"

if "%NEEDS_INSTALL%"=="0" goto :run
echo [start] 正在安装 requirements.txt...
"%PYTHON_BIN%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail_install

:run
"%PYTHON_BIN%" main.py
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

:fail_venv
echo [start] 无法创建 .venv：请确认 python 已加入 PATH。
endlocal & exit /b 1

:fail_install
echo [start] 依赖安装失败。
endlocal & exit /b 1
