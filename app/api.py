import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .config import Settings
from .models import ChatRequest, ChatResponse, Feedback
from .service import MovieService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    app.state.service = MovieService(Settings())
    yield


app = FastAPI(title="Movie Picker API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "mode": app.state.service.settings.app_mode}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        return app.state.service.chat(request)
    except Exception:
        logger.exception("Recommendation failed")
        raise HTTPException(503, "추천 서비스에 연결하지 못했어요. API 설정과 네트워크를 확인한 뒤 다시 시도해 주세요.") from None


@app.post("/feedback", status_code=201)
def feedback(request: Feedback):
    try:
        app.state.service.feedback(request)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"saved": True}
