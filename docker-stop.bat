@echo off
cd /d "%~dp0"
docker compose down
echo Stopped. Your data is kept safely in the Docker volume.
pause
