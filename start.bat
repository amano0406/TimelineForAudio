@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "DOCKER_DESKTOP_URL=https://docs.docker.com/desktop/setup/install/windows-install/"
set "DOCKER_DESKTOP_EXE="

if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" set "DOCKER_DESKTOP_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not defined DOCKER_DESKTOP_EXE if exist "%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe" set "DOCKER_DESKTOP_EXE=%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe"
if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"

where docker >nul 2>&1
if errorlevel 1 (
  if defined DOCKER_DESKTOP_EXE (
    echo Docker Desktop appears to be installed, but docker.exe is not available from this command prompt.
    echo Open Docker Desktop once, then reopen this start.bat.
    start "" "!DOCKER_DESKTOP_EXE!" >nul 2>&1
  ) else (
    echo Docker Desktop is not installed, or docker.exe is not on PATH.
    echo Download and install Docker Desktop here:
    echo   %DOCKER_DESKTOP_URL%
    start "" "%DOCKER_DESKTOP_URL%" >nul 2>&1
  )
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  if defined DOCKER_DESKTOP_EXE (
    echo Starting Docker Desktop. This can take a minute...
    start "" "!DOCKER_DESKTOP_EXE!" >nul 2>&1
    call :WaitForDockerEngine
    if errorlevel 1 (
      echo Docker Desktop did not become ready in time.
      exit /b 1
    )
  ) else (
    echo Docker Desktop is installed but the Docker engine is not ready.
    exit /b 1
  )
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example.
)

set "COMPOSE_GPU_FILE="
where nvidia-smi >nul 2>&1
if not errorlevel 1 (
  set "COMPOSE_GPU_FILE=-f docker-compose.gpu.yml"
  echo NVIDIA GPU detected. Starting GPU worker image.
)

echo Building and starting the worker container...
docker compose -f docker-compose.yml %COMPOSE_GPU_FILE% up --build -d worker
if errorlevel 1 (
  echo docker compose failed.
  exit /b 1
)

echo.
echo TimelineForAudio worker is running.
echo.
echo CLI examples:
echo   set PYTHONPATH=worker\src
echo   python -m timeline_for_audio_worker settings status
echo   python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3"
echo   python -m timeline_for_audio_worker jobs list
echo.
echo Docker status:
docker compose ps
exit /b 0

:WaitForDockerEngine
set /a DOCKER_WAIT_ATTEMPT=0
:wait_for_docker_engine_loop
set /a DOCKER_WAIT_ATTEMPT+=1
docker info >nul 2>&1
if not errorlevel 1 exit /b 0
if !DOCKER_WAIT_ATTEMPT! GEQ 60 exit /b 1
powershell -NoLogo -NoProfile -Command "Start-Sleep -Seconds 2" >nul 2>&1
goto wait_for_docker_engine_loop
