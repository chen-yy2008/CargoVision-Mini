@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 找不到项目的 .venv\Scripts\python.exe。
    echo 请按 README 的安装说明准备已有 Python 环境。本入口不会自动安装或修改环境。
    pause
    exit /b 1
)
if not exist ".cache" mkdir ".cache"
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -c "import tkinter, cv2, numpy" >".cache\launcher_bootstrap.log" 2>&1
if errorlevel 1 (
    echo 项目环境无法运行 Tkinter、OpenCV 或 NumPy。没有执行安装或环境修改。
    echo 诊断信息如下，也保存在 .cache\launcher_bootstrap.log：
    type ".cache\launcher_bootstrap.log"
    pause
    exit /b 1
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launcher.py"
) else (
    ".venv\Scripts\python.exe" "%~dp0launcher.py"
    if errorlevel 1 pause
)
endlocal
