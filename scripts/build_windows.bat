@echo off
REM ClipCleaner Windows 打包：生成 ClipCleaner.exe（需在 Windows 10/11 上运行）
setlocal
cd /d "%~dp0.."

echo ==^> 生成应用图标
python scripts\generate_icon.py
if errorlevel 1 exit /b 1

echo ==^> 安装依赖
python -m pip install -q -r requirements.txt
if errorlevel 1 exit /b 1

echo ==^> PyInstaller 打包
python -m PyInstaller build.spec --noconfirm --clean
if errorlevel 1 exit /b 1

echo ==^> 创建 ZIP 分发包
powershell -Command "Compress-Archive -Path 'dist\ClipCleaner.exe' -DestinationPath 'dist\ClipCleaner-Windows.zip' -Force"

echo.
echo 打包完成:
echo   dist\ClipCleaner.exe
echo   dist\ClipCleaner-Windows.zip
echo 将 zip 或 exe 复制到其他 Windows 电脑即可双击运行。
echo 首次运行若被 SmartScreen 拦截，请点击「更多信息」-^>「仍要运行」。
endlocal
