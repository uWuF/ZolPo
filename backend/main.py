"""
ZolPo entry point (thin shim).

The application now lives in the `app` package; this module just re-exports the
FastAPI instance so existing launch configs keep working:

    uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8020
"""

from app.api import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8020, reload=True)
