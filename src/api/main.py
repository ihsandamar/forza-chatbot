# src/api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from src.api.routes import chat, health, configuration, metrics, sessions
from src.api.routes.export import router as export_router
from src.api.utils.error_handlers import validation_exception_handler, general_exception_handler


def build_fastapi_app(config) -> FastAPI:
    """
    FastAPI app factory.

    Args:
        config: AppConfig from get_config(). Passed in so this function
                has no I/O side-effects (no config loading here).

    Returns:
        Fully configured FastAPI application, ready for uvicorn.
    """
    app = FastAPI(
        title="Chatbot API",
        description="FastAPI-based chatbot service with LangGraph integration",
        version="1.0.0",
    )

    @app.on_event("startup")
    async def startup_event():
        """
        Pre-warm heavy resources at startup.

        Config is already loaded by the launcher — only I/O-heavy tasks live here.
        """
        # Preload embedding model to avoid HuggingFace timeouts on first request
        try:
            from src.factories.embedding_factory import preload_embedding_model
            print("[STARTUP] Preloading embedding model (first run may take 1-2 minutes)...")
            model_loaded = preload_embedding_model()
            if model_loaded:
                print("[STARTUP] [OK] Embedding model cached successfully")
            else:
                print("[STARTUP] [WARN] Embedding model preload failed (will retry on first use)")
        except Exception as e:
            print(f"[STARTUP] [WARN] Failed to preload embedding model: {e}")

        # Start background table cleanup
        try:
            import os
            from src.graphs.report_agent.table_registry import get_table_registry
            db_connection_string = os.getenv("DATABASE_URL")
            if db_connection_string:
                registry = get_table_registry()
                registry.start_background_cleanup(
                    db_connection_string=db_connection_string,
                    interval=300,
                )
                print("[STARTUP] Started background table cleanup (interval=300s)")
            else:
                print("[STARTUP] Warning: DATABASE_URL not set, skipping background table cleanup")
        except Exception as e:
            print(f"[STARTUP] Warning: Failed to start background table cleanup: {e}")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Routers
    app.include_router(health.router, prefix="/api/health", tags=["Health"])
    app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    app.include_router(configuration.router, prefix="/api/configuration", tags=["Configuration"])
    app.include_router(metrics.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(export_router, prefix="/api")

    @app.get("/")
    async def root():
        return {"message": "Chatbot API", "version": "1.0.0", "docs": "/docs"}

    return app
