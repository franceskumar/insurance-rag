"""HTTP API and frontend. Run with `python -m uvicorn app.main:app`."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .ingestion import MAX_BYTES, DocumentError
from .rag import Settings, ask
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=8)

    @field_validator("question")
    @classmethod
    def meaningful_question(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a question with at least 3 characters.")
        return value


def create_app(db_path: Path | None = None, settings: Settings | None = None, seed_demo: bool = True) -> FastAPI:
    load_dotenv(ROOT / ".env")
    selected_settings = settings or Settings.from_env()
    selected_path = db_path or Path(os.getenv("INSURANCE_DB", str(ROOT / "data" / "policylens.sqlite3")))

    @asynccontextmanager
    async def lifespan(application):
        application.state.store = Store(selected_path)
        if seed_demo:
            application.state.store.seed(ROOT / "sample_policies")
        yield

    application = FastAPI(title="PolicyLens · Insurance RAG", version="1.0.0", lifespan=lifespan)
    # This is a local, single-user project. Host checking also blocks DNS rebinding.
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])

    @application.middleware("http")
    async def response_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            if origin.rstrip("/") != str(request.base_url).rstrip("/"):
                raise_error = {"detail": "Cross-origin writes are not allowed."}
                from fastapi.responses import JSONResponse
                return JSONResponse(raise_error, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path in {"/docs", "/redoc"}:
            # FastAPI's optional API explorers load their bundled UI from a CDN.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
                "frame-ancestors 'self'"
            )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/api/status")
    def status(request: Request):
        store = request.app.state.store
        documents = store.documents()
        return {"status": "ready", "documents": len(documents),
                "chunks": sum(d["chunk_count"] for d in documents),
                "questions": len(store.history()), **selected_settings.public()}

    @application.get("/api/documents")
    def documents(request: Request):
        return request.app.state.store.documents()

    @application.post("/api/documents", status_code=201)
    async def upload(request: Request, file: UploadFile):
        try:
            content = await file.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise HTTPException(413, "The maximum file size is 15 MB.")
            return await run_in_threadpool(request.app.state.store.ingest, file.filename or "document.txt", content)
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()

    @application.get("/api/documents/{document_id}")
    def document(request: Request, document_id: str):
        store = request.app.state.store
        result = store.document(document_id)
        if not result:
            raise HTTPException(404, "Document not found.")
        return {**result, "passages": store.chunks([document_id])}

    @application.delete("/api/documents/{document_id}", status_code=204)
    def delete(request: Request, document_id: str):
        if not request.app.state.store.delete(document_id):
            raise HTTPException(404, "Document not found.")

    @application.post("/api/ask")
    async def question(request: Request, body: Question):
        store = request.app.state.store
        known = {doc["id"] for doc in store.documents()}
        if set(body.document_ids) - known:
            raise HTTPException(404, "A selected document no longer exists. Refresh the document list.")
        return await ask(store, selected_settings, body.question, body.document_ids, body.top_k)

    @application.get("/api/history")
    def history(request: Request):
        return request.app.state.store.history()

    @application.delete("/api/history", status_code=204)
    def clear_history(request: Request):
        request.app.state.store.clear_history()

    @application.get("/")
    def index():
        return FileResponse(ROOT / "app" / "static" / "index.html")

    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
    return application


app = create_app()
