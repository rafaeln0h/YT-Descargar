@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cls

cd /d "%~dp0"
set "ROOT=%cd%"
set "APP_PORT=5000"
set "APP_HOST=127.0.0.1"
set "DEBUG_FLAG="
set "LOG_DIR=%ROOT%\logs"
set "START_TS=%DATE%_%TIME%"
set "START_TS=%START_TS:/=-%"
set "START_TS=%START_TS::=-%"
set "START_TS=%START_TS: =0%"
set "APP_LOG=%LOG_DIR%\launcher_%START_TS%.log"

if not "%~1"=="" set "APP_PORT=%~1"
if /I "%~2"=="debug" set "DEBUG_FLAG=--debug"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

echo ==========================================
echo   YT-Descargar 0.013 - Launcher
echo ==========================================
echo [INFO] Carpeta: %ROOT%
echo [INFO] Log de inicio: %APP_LOG%
echo.

call :detect_python || goto :fatal
call :check_python_version || goto :fatal
call :ensure_venv || goto :fatal
call :install_deps || goto :fatal
call :verify_imports || goto :fatal
call :ensure_ffmpeg || goto :fatal
call :choose_free_port || goto :fatal
if defined APP_ALREADY_RUNNING (
    echo [INFO] YT-Descargar ya esta abierto en http://%APP_HOST%:%APP_PORT%
    echo [INFO] No se iniciara una segunda instancia que comparta el historial.
    exit /b 0
)

echo.
echo [OK] Todo listo.
echo [INFO] URL local: http://%APP_HOST%:%APP_PORT%
echo [INFO] Para cerrar: Ctrl + C
echo.

call :write_runtime_report
echo [RUN] Iniciando aplicacion...
"%PY_EXE%" app_playlist.py --host %APP_HOST% --port %APP_PORT% %DEBUG_FLAG% 1>>"%APP_LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] La aplicacion termino con codigo %EXIT_CODE%.
    echo [TIP] Revisa el log: %APP_LOG%
    powershell -NoProfile -Command "if (Test-Path '%APP_LOG%') { Get-Content '%APP_LOG%' -Tail 40 }"
    pause
)
exit /b %EXIT_CODE%

:detect_python
echo [CHECK] Detectando Python...
set "PY_EXE="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; print(sys.executable)" >nul 2>&1
    if not errorlevel 1 set "PY_EXE=py -3"
)

if not defined PY_EXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; print(sys.executable)" >nul 2>&1
        if not errorlevel 1 set "PY_EXE=python"
    )
)

if not defined PY_EXE (
    echo [ERROR] No se encontro una instalacion funcional de Python.
    echo [TIP] Un acceso de Microsoft Store o un entorno virtual roto no es suficiente.
    echo Instala Python desde: https://www.python.org/downloads/
    exit /b 1
)

echo [OK] Python detectado: %PY_EXE%
exit /b 0

:check_python_version
echo [CHECK] Validando version de Python (3.11+)...
%PY_EXE% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Esta app requiere Python 3.11 o superior.
    %PY_EXE% --version
    exit /b 1
)
for /f "delims=" %%v in ('%PY_EXE% --version 2^>^&1') do echo [OK] %%v
exit /b 0

:ensure_venv
echo [CHECK] Preparando entorno virtual...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; print(sys.executable)" >nul 2>&1
    if errorlevel 1 (
        set "BROKEN_VENV=.venv_broken_%START_TS%"
        echo [AVISO] El entorno .venv existe pero su Python ya no esta disponible.
        echo [RECOVERY] Se conservara como !BROKEN_VENV! y se creara uno nuevo.
        move ".venv" "!BROKEN_VENV!" >nul
        if errorlevel 1 (
            echo [ERROR] No se pudo apartar el entorno virtual roto.
            exit /b 1
        )
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creando .venv...
    %PY_EXE% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
set "PY_EXE=python"
for /f "delims=" %%v in ('python --version 2^>^&1') do echo [OK] Entorno activo con %%v
exit /b 0

:install_deps
echo [CHECK] Instalando/actualizando dependencias...
python -m pip install --disable-pip-version-check -q --upgrade pip setuptools wheel
if exist "requirements.txt" (
    python -m pip install --disable-pip-version-check -q --upgrade --upgrade-strategy only-if-needed -r requirements.txt
) else (
    python -m pip install --disable-pip-version-check -q --upgrade flask flask-cors "yt-dlp[default,curl-cffi,deno]" mutagen musicbrainzngs pillow requests
)
if errorlevel 1 (
    echo [ERROR] Fallo al instalar dependencias.
    exit /b 1
)
exit /b 0

:verify_imports
echo [CHECK] Verificando modulos clave...
python -c "import flask, flask_cors, yt_dlp, mutagen, requests, musicbrainzngs; import app_playlist; print('ok')" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se pudieron importar todos los modulos.
    echo [TIP] Mira el detalle en el log: %APP_LOG%
    python -c "import flask, flask_cors, yt_dlp, mutagen, requests, musicbrainzngs; import app_playlist" 1>>"%APP_LOG%" 2>&1
    echo Ejecuta manualmente: python -m pip install -r requirements.txt
    exit /b 1
)
echo [OK] Modulos cargados correctamente.
exit /b 0

:ensure_ffmpeg
echo [CHECK] Verificando FFmpeg...
python -c "from setup_ffmpeg import ensure_ffmpeg; import sys; p=ensure_ffmpeg(); sys.exit(0 if p else 1)"
if errorlevel 1 (
    echo [ERROR] No se pudo configurar FFmpeg.
    exit /b 1
)
exit /b 0

:choose_free_port
echo [CHECK] Comprobando si la aplicacion ya esta activa...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { $health=Invoke-RestMethod -Uri 'http://%APP_HOST%:%APP_PORT%/api/health' -TimeoutSec 2; if ($health.service -eq 'ymd') { exit 0 } } catch {}; try { $response=Invoke-WebRequest -UseBasicParsing -Uri 'http://%APP_HOST%:%APP_PORT%/api/history' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
    set "APP_ALREADY_RUNNING=1"
    exit /b 0
)

echo [CHECK] Buscando puerto libre (inicio en %APP_PORT%)...
for /f %%p in ('powershell -NoProfile -Command "$start=[int]'%APP_PORT%'; for($p=$start; $p -le 65535; $p++){ try { $l=[System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch {} }"') do set "FREE_PORT=%%p"

if not defined FREE_PORT (
    echo [ERROR] No se encontro puerto libre.
    exit /b 1
)
if not "%FREE_PORT%"=="%APP_PORT%" (
    echo [AVISO] Puerto %APP_PORT% ocupado. Se usara %FREE_PORT%.
)
set "APP_PORT=%FREE_PORT%"
exit /b 0

:write_runtime_report
(
    echo ==========================================
    echo Launcher iniciado: %DATE% %TIME%
    echo Carpeta: %ROOT%
    echo Host: %APP_HOST%
    echo Puerto: %APP_PORT%
    echo Python: %PY_EXE%
    echo ==========================================
)>"%APP_LOG%"

echo [CHECK] Validando render y endpoints basicos...
python -c "from app_playlist import app; c=app.test_client(); assert c.get('/').status_code==200; assert c.get('/api/history').status_code==200; assert c.get('/api/queue').status_code==200; print('smoke ok')" 1>>"%APP_LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] La app no paso la prueba rapida de inicio.
    echo [TIP] Mira el log: %APP_LOG%
    exit /b 1
)

echo [OK] Smoke test correcto.
start "" "http://%APP_HOST%:%APP_PORT%"
exit /b 0

:fatal
echo.
echo [FATAL] No se pudo iniciar la aplicacion.
if exist "%APP_LOG%" (
    echo [TIP] Ultimas lineas del log:
    powershell -NoProfile -Command "Get-Content '%APP_LOG%' -Tail 40"
)
pause
exit /b 1
