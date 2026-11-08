@echo off
setlocal
cd /d "%~dp0"
title Shiva Traders Payroll (Docker)
where docker >nul 2>nul
if errorlevel 1 goto :no_docker
docker info >nul 2>nul
if errorlevel 1 goto :not_running
echo Starting PostgreSQL and the app (first time downloads images, 2-5 minutes)...
docker compose up -d --build
if errorlevel 1 goto :fail
echo Waiting for the app to start...
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://localhost:5000/login -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto :ready
if %tries% geq 60 goto :slow
timeout /t 2 /nobreak >nul
goto :wait
:ready
echo.
echo ========================================================
echo   App is running:  http://localhost:5000
for /f "delims=" %%a in ('powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | Select-Object -First 1).IPv4Address.IPAddress"') do echo   Phones on same Wi-Fi:  http://%%a:5000
echo   Login: admin / admin123  (change in docker-compose.yml before first start)
echo   It keeps running in the background - you can close this window.
echo   To stop: double-click docker-stop.bat
echo ========================================================
start "" http://localhost:5000
pause
exit /b 0

:no_docker
echo [ERROR] Docker is not installed.
echo   Install Docker Desktop: https://www.docker.com/products/docker-desktop/
echo   Restart the PC after installing, open Docker Desktop once, then run this again.
pause
exit /b 1
:not_running
echo [ERROR] Docker Desktop is not running. Open Docker Desktop from the Start menu,
echo   wait until it says "Engine running", then run this again.
pause
exit /b 1
:slow
echo The app is taking long to start. Showing logs:
docker compose logs --tail 40 web
pause
exit /b 1
:fail
echo [ERROR] docker compose failed - see the message above.
pause
exit /b 1
