@echo off
REM ============================================
REM Simple API Build Script
REM Builds the FastAPI application as executable
REM ============================================

echo.
echo ============================================
echo 🚀 Building Chatbot API Executable
echo ============================================
echo.

REM Clean previous builds
if exist "dist\chatbot-api" (
    echo 🧹 Cleaning previous build...
    rmdir /s /q "dist\chatbot-api"
)

if exist "build" (
    rmdir /s /q "build"
)

echo.
echo 📦 Building with PyInstaller...
echo.

REM Build with PyInstaller
pyinstaller --clean --noconfirm api_app.spec

if errorlevel 1 (
    echo.
    echo ❌ Build failed!
    pause
    exit /b 1
)

echo.
echo 📁 Copying configuration files...
echo.

REM Create config directory in dist
if not exist "dist\chatbot-api\config" mkdir "dist\chatbot-api\config"

REM Copy config file
if exist "config\config.yaml" (
    copy "config\config.yaml" "dist\chatbot-api\config\" > nul
    echo ✅ Copied config.yaml
) else (
    echo ⚠️  WARNING: config/config.yaml not found
)

REM Copy .env file (if exists)
if exist "config\.env" (
    copy "config\.env" "dist\chatbot-api\.env" > nul
    echo ✅ Copied .env file
) else (
    if exist ".env" (
        copy ".env" "dist\chatbot-api\.env" > nul
        echo ✅ Copied .env file from root
    ) else (
        echo ⚠️  WARNING: .env file not found - you'll need to create one
    )
)

REM Copy vectorstore data for vegaforza_navigation graph
echo.
echo 📦 Copying vectorstore data...
if exist "data\vector_index" (
    xcopy "data\vector_index" "dist\chatbot-api\data\vector_index\" /E /I /Y > nul
    echo ✅ Copied vectorstore data
) else (
    echo ⚠️  WARNING: data/vector_index not found - vegaforza_navigation graph may not work
)

REM Create example .env if it doesn't exist
if not exist "dist\chatbot-api\.env" (
    echo OPENAI_API_KEY=your-api-key-here> "dist\chatbot-api\.env.example"
    echo API_PORT=8000>> "dist\chatbot-api\.env.example"
    echo API_HOST=0.0.0.0>> "dist\chatbot-api\.env.example"
    echo 📝 Created .env.example - please rename to .env and configure
)

echo.
echo ============================================
echo ✅ Build Complete!
echo ============================================
echo.
echo 📍 Output location: dist\chatbot-api\
echo 🚀 Executable: dist\chatbot-api\chatbot-api.exe
echo.
echo Next steps:
echo 1. Navigate to: dist\chatbot-api\
echo 2. Ensure .env and config\config.yaml are configured
echo 3. Run: chatbot-api.exe
echo.
echo ============================================
pause
