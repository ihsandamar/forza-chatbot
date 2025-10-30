"""
Simple API Entry Point for PyInstaller
Runs the FastAPI application with uvicorn
"""
import sys
import os
from pathlib import Path

# Add current directory to path for imports
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    application_path = Path(sys.executable).parent
else:
    # Running as script
    application_path = Path(__file__).parent

os.chdir(application_path)
sys.path.insert(0, str(application_path))

# Now import the FastAPI app
from src.api.main import app

if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv

    # Load .env file first
    env_path = application_path / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[OK] Loaded environment from: {env_path}")
    else:
        print(f"[WARNING] .env file not found at {env_path}, using defaults")
        load_dotenv()  # Try to load from default locations

    # Get port from environment or use default
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    print("=" * 60)
    print("[START] Starting Chatbot API Server")
    print("=" * 60)
    print(f"[DIR] Working Directory: {application_path}")
    print(f"[HOST] Server: http://{host}:{port}")
    print(f"[DOCS] API Docs: http://{host}:{port}/docs")
    print(f"[HEALTH] Health Check: http://{host}:{port}/api/health")
    print("=" * 60)
    print()

    # Check if config files exist
    config_file = application_path / "config" / "config.yaml"
    env_file = application_path / ".env"

    if not config_file.exists():
        print(f"[WARNING] Config file not found at {config_file}")
        print("   Please ensure config/config.yaml exists next to the executable")
    else:
        print(f"[OK] Config file found: {config_file}")

    if not env_file.exists():
        print(f"[WARNING] .env file not found at {env_file}")
        print("   Please ensure .env exists next to the executable")
    else:
        print(f"[OK] .env file found: {env_file}")

    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    print()

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\n[INFO] Server stopped by user")
    except Exception as e:
        print(f"\n\n[ERROR] Error starting server: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
