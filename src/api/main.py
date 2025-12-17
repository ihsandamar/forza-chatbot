from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from src.api.routes import chat, health, configuration
from src.api.utils.error_handlers import validation_exception_handler, general_exception_handler
from src.services.config_loader import ConfigLoader

# Create FastAPI app
app = FastAPI(
    title="Chatbot API",
    description="FastAPI-based chatbot service with LangGraph integration",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """
    Pre-load configuration on startup to avoid blocking I/O in async contexts.

    This ensures that when LangGraph calls graph functions, the config is already
    cached and won't trigger blocking I/O detection.
    """
    try:
        # Pre-load config synchronously in startup event
        ConfigLoader.load_config()
    except Exception as e:
        print(f"Warning: Failed to pre-load config on startup: {e}")
        # Continue anyway - config will be loaded lazily on first use

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include routers
app.include_router(health.router, prefix="/api/health", tags=["Health"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(configuration.router, prefix="/api/configuration", tags=["Configuration"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Chatbot API",
        "version": "1.0.0",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    import os
    from dotenv import load_dotenv

    load_dotenv()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
