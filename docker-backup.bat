@echo off
setlocal
cd /d "%~dp0"
if not exist backups mkdir backups
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%t
docker compose exec -T db pg_dump -U postgres shiva_payroll > "backups\shiva_payroll_%TS%.sql"
if errorlevel 1 (echo Backup FAILED - is the app running?) else (echo Database saved to backups\shiva_payroll_%TS%.sql)
docker compose cp web:/app/uploads "backups\uploads_%TS%" >nul 2>nul && echo Bill photos saved to backups\uploads_%TS%
pause
