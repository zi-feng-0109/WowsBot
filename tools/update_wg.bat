@echo off
REM update_wg.bat — 双击运行(建议右键「以管理员身份运行」)。
REM 真正的逻辑在同目录的 update_wg.ps1;这里只是个启动器,
REM 因为内嵌的 PowerShell 没法单独调用测试。
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_wg.ps1" %*
echo.
pause
