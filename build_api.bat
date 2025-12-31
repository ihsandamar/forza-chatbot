@echo off
REM ============================================
REM Incremental API Build Script
REM Smart caching: only full rebuild when packages change
REM ============================================

setlocal enabledelayedexpansion

echo.
echo ============================================
echo Building Chatbot API Executable
echo ============================================
echo.

REM ============================================
REM Check if incremental build is possible
REM ============================================
set "CACHE_FILE=.build_cache"
set "REQUIREMENTS_FILE=requirements.txt"
set "CLEAN_FLAG=--clean"
set "SKIP_BUILD=0"

echo [*] Checking for changes...
echo.

REM Check if requirements.txt exists
if not exist "%REQUIREMENTS_FILE%" (
    echo [!] WARNING: requirements.txt not found
    set "CLEAN_FLAG=--clean"
    goto :CheckPythonFiles
)

REM Calculate current requirements hash
for /f "delims=" %%A in ('certutil -hashfile "%REQUIREMENTS_FILE%" MD5 ^| findstr /v ":" ^| findstr /v "MD5"') do set "CURRENT_REQ_HASH=%%A"
set "CURRENT_REQ_HASH=!CURRENT_REQ_HASH: =!"

REM Check if cache file exists and read previous hash
if exist "%CACHE_FILE%" (
    set /p PREV_REQ_HASH=<%CACHE_FILE%

    if "!CURRENT_REQ_HASH!"=="!PREV_REQ_HASH!" (
        echo [+] Packages unchanged - using cached build
        set "CLEAN_FLAG="
    ) else (
        echo [*] Packages changed - full rebuild required
        set "CLEAN_FLAG=--clean"
    )
) else (
    echo [*] First build - full rebuild
    set "CLEAN_FLAG=--clean"
)

:CheckPythonFiles
REM Check if any Python files changed
if exist "dist\chatbot-api\chatbot-api.exe" (
    if "!CLEAN_FLAG!"=="" (
        echo [*] Checking Python files for changes...

        REM Find if any Python file is newer than EXE
        set "HAS_CHANGES=0"
        for /r "src" %%F in (*.py) do (
            xcopy /L /D /Y "%%F" "dist\chatbot-api\chatbot-api.exe" 2>nul | findstr /C:"File(s)" >nul
            if not errorlevel 1 set "HAS_CHANGES=1"
        )

        if "!HAS_CHANGES!"=="0" (
            for %%F in ("api_app.py" "api_app.spec") do (
                if exist "%%F" (
                    xcopy /L /D /Y "%%F" "dist\chatbot-api\chatbot-api.exe" 2>nul | findstr /C:"File(s)" >nul
                    if not errorlevel 1 set "HAS_CHANGES=1"
                )
            )
        )

        if "!HAS_CHANGES!"=="0" (
            echo [+] No Python files changed since last build
            echo [*] Skipping build - using existing executable
            set "SKIP_BUILD=1"
            goto :CopyFiles
        ) else (
            echo [*] Python files changed - incremental rebuild
        )
    )
) else (
    echo [*] No existing build found
)

echo.

REM ============================================
REM Clean previous dist (but keep build cache)
REM ============================================
if "%SKIP_BUILD%"=="0" (
    if exist "dist\chatbot-api" (
        echo [*] Cleaning previous distribution...
        rmdir /s /q "dist\chatbot-api"
    )

    REM Only clean build cache if packages changed
    if "%CLEAN_FLAG%"=="--clean" (
        echo [*] Cleaning build cache - packages changed
        if exist "build" rmdir /s /q "build"
    ) else (
        echo [+] Keeping build cache for faster rebuild
    )

    echo.
    echo [*] Building with PyInstaller...
    if "%CLEAN_FLAG%"=="--clean" (
        echo     Mode: FULL BUILD - packages changed
    ) else (
        echo     Mode: INCREMENTAL BUILD - using cache
    )
    echo.

    REM Build with PyInstaller
    if "%CLEAN_FLAG%"=="--clean" (
        pyinstaller --clean --noconfirm api_app.spec
    ) else (
        pyinstaller --noconfirm api_app.spec
    )

    if errorlevel 1 (
        echo.
        echo [!] Build failed!
        pause
        exit /b 1
    )

    REM Save current requirements hash to cache
    echo !CURRENT_REQ_HASH!>%CACHE_FILE%
    echo [+] Build cache updated
)

:CopyFiles
echo.
echo [*] Copying configuration files...
echo.

REM Create config directory in dist
if not exist "dist\chatbot-api\config" mkdir "dist\chatbot-api\config"

REM Copy config file
if exist "config\config.yaml" (
    copy "config\config.yaml" "dist\chatbot-api\config\" > nul
    echo [+] Copied config.yaml
) else (
    echo [!] WARNING: config/config.yaml not found
)

REM Copy .env file (if exists)
if exist "config\.env" (
    copy "config\.env" "dist\chatbot-api\.env" > nul
    echo [+] Copied .env file
) else (
    if exist ".env" (
        copy ".env" "dist\chatbot-api\.env" > nul
        echo [+] Copied .env file from root
    ) else (
        echo [!] WARNING: .env file not found - you'll need to create one
    )
)

REM Copy vectorstore data for vegaforza_navigation graph
echo.
echo [*] Copying vectorstore data...
if exist "data\vector_index" (
    xcopy "data\vector_index" "dist\chatbot-api\data\vector_index\" /E /I /Y > nul
    echo [+] Copied vectorstore data
) else (
    echo [!] WARNING: data/vector_index not found - vegaforza_navigation graph may not work
)

REM Create example .env if it doesn't exist
if not exist "dist\chatbot-api\.env" (
    echo OPENAI_API_KEY=your-api-key-here> "dist\chatbot-api\.env.example"
    echo API_PORT=8000>> "dist\chatbot-api\.env.example"
    echo API_HOST=0.0.0.0>> "dist\chatbot-api\.env.example"
    echo [*] Created .env.example - please rename to .env and configure
)

echo.
echo ============================================
if "%SKIP_BUILD%"=="1" (
    echo [SUCCESS] Build Skipped - No Changes Detected!
) else (
    echo [SUCCESS] Build Complete!
)
echo ============================================
echo.
echo Output location: dist\chatbot-api\
echo Executable: dist\chatbot-api\chatbot-api.exe
echo.
echo Build optimization tips:
echo    - Python file changes: Incremental build (fast ~2-5 min)
echo    - Package changes: Full rebuild (slow ~10-15 min)
echo    - No changes: Build skipped (instant ~1 sec)
echo    - Force full rebuild: Delete .build_cache file
echo.
echo Next steps:
echo 1. Navigate to: dist\chatbot-api\
echo 2. Ensure .env and config\config.yaml are configured
echo 3. Run: chatbot-api.exe
echo.
echo ============================================
pause
