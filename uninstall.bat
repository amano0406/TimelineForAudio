@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "COMPOSE_PROJECT=audio2timeline"
set "APPDATA_VOLUME=%COMPOSE_PROJECT%_app-data"
set "OUTPUTS_VOLUME=%COMPOSE_PROJECT%_outputs"
set "UPLOADS_VOLUME=%COMPOSE_PROJECT%_uploads"
set "HF_CACHE_VOLUME=%COMPOSE_PROJECT%_hf-cache"
set "TORCH_CACHE_VOLUME=%COMPOSE_PROJECT%_torch-cache"

where docker >nul 2>&1
if errorlevel 1 (
  echo docker.exe was not found on PATH.
  echo Install Docker Desktop first, then try again.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is installed but the Docker engine is not ready.
  echo Start Docker Desktop and wait until the engine is running, then try again.
  exit /b 1
)

echo.
echo audio2timeline uninstall
echo.
echo This will remove:
echo   - Docker containers for this project
echo   - Docker images built for this project
echo   - temporary Docker volumes for this project
echo   - Docker network for this project
echo.
echo Optional:
echo   - delete saved app data volume ^(includes token and settings^)
if exist ".env" (
  echo   - delete local .env
)
echo.

call :confirm_yes "Continue with uninstall? (y/n): "
if errorlevel 1 (
  echo Uninstall canceled.
  exit /b 1
)

echo.
echo Stopping and removing Docker resources...
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down --rmi local --remove-orphans <nul
if errorlevel 1 (
  echo Docker cleanup failed.
  exit /b 1
)

call :remove_volume_if_exists "!UPLOADS_VOLUME!"
if errorlevel 1 exit /b 1
call :remove_volume_if_exists "!OUTPUTS_VOLUME!"
if errorlevel 1 exit /b 1
call :remove_volume_if_exists "!HF_CACHE_VOLUME!"
if errorlevel 1 exit /b 1
call :remove_volume_if_exists "!TORCH_CACHE_VOLUME!"
if errorlevel 1 exit /b 1

echo.
echo Saved app data volume:
echo   !APPDATA_VOLUME!
echo This includes your saved Hugging Face token and app settings.
call :confirm_yes "Delete saved token and settings too? (y/n): "
if not errorlevel 1 (
  call :remove_volume_if_exists "!APPDATA_VOLUME!"
  if errorlevel 1 exit /b 1
  echo Deleted saved app data volume.
) else (
  echo Kept saved token and settings.
)

echo Docker resources removed.

if exist ".env" (
  echo.
  call :confirm_yes "Delete local .env as well? (y/n): "
  if not errorlevel 1 (
    del /q ".env"
    echo Deleted .env
  ) else (
    echo Kept .env
  )
)

echo.
echo Uninstall completed.
exit /b 0

:remove_volume_if_exists
set "VOLUME_NAME=%~1"
if not defined VOLUME_NAME exit /b 0

docker volume inspect "!VOLUME_NAME!" >nul 2>&1
if errorlevel 1 exit /b 0

docker volume rm "!VOLUME_NAME!" >nul
if errorlevel 1 (
  echo Failed to remove Docker volume: !VOLUME_NAME!
  exit /b 1
)
echo Removed Docker volume: !VOLUME_NAME!

exit /b 0

:confirm_yes
set "PROMPT_TEXT=%~1"
echo %PROMPT_TEXT%
choice /c yn /n
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 0
exit /b 1
