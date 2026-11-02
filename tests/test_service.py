from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.config import Settings
from app.models import ChatRequest, Feedback
from app.service import MovieService


@pytest.fixture
def service(tmp_path):
    return MovieService(Settings(app_mode="demo", data_dir=str(tmp_path), tmdb_api_key=""))


def request(message, session=None, **kwargs):
    return ChatRequest(session_id=session or uuid4(), message=message, **kwargs)


def test_healing_and_time_constraint(service):
    result = service.chat(request("회사에서 지쳐서 편안하게 쉬고 싶어. 105분 이내로 추천해줘"))
    assert result.recommendations
    assert all(m.runtime <= 105 for m in result.recommendations)
    assert "little-forest" in [m.movie_id for m in result.recommendations]
    assert all(not m.providers for m in result.recommendations)


def test_memory_and_isolation(service):
    session = uuid4()
    service.chat(request("편안하게 쉬고 싶어. 90분 이내로", session))
    second = service.chat(request("혼자 볼 거야", session))
    assert second.preferences.mood == "힐링"
    assert second.preferences.max_minutes == 90
    assert all(m.runtime <= 90 for m in second.recommendations)
    separate = service.chat(request("혼자 볼 거야"))
    assert not separate.recommendations
    assert "싶으세요" in separate.message


def test_impossible_limit_does_not_relax(service):
    result = service.chat(request("웃고 싶어", max_minutes=20))
    assert not result.recommendations


def test_unknown_ott_never_claimed(service):
    result = service.chat(request("편안한 영화", providers=["넷플릭스"]))
    assert not result.recommendations
    assert result.warnings


def test_excluded_genre_and_duration(service):
    result = service.chat(request("몰입하고 싶어. 액션은 싫어. 2시간 반 이내"))
    assert result.preferences.max_minutes == 150
    assert "액션" in result.preferences.avoid
    assert all("액션" not in m.genres for m in result.recommendations)


def test_feedback_persistence_and_validation(service):
    feedback = Feedback(session_id=uuid4(), movie_id="chef", rating=5, comment="좋았어요")
    service.feedback(feedback)
    with service.db() as conn:
        assert conn.execute("SELECT rating, comment FROM feedback").fetchone() == (5, "좋았어요")
    with pytest.raises(ValueError):
        service.feedback(feedback.model_copy(update={"movie_id": "unknown"}))
    with pytest.raises(ValidationError):
        request("  ")


def test_api_contract(tmp_path, monkeypatch):
    from app.api import app
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("TMDB_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health").json()["mode"] == "demo"
        result = client.post("/chat", json={"session_id": str(uuid4()), "message": "가볍게 웃고 싶어"})
        assert result.status_code == 200
        assert len(result.json()["recommendations"]) == 2
        assert client.post("/chat", json={"session_id": "invalid", "message": "hi"}).status_code == 422


def test_provider_aliases():
    assert MovieService.provider_matches(["넷플릭스"], ["Netflix Standard with Ads"])
    assert not MovieService.provider_matches(["왓챠"], ["Netflix"])


def test_failed_turn_preserves_previous_preferences(service, monkeypatch):
    session = uuid4()
    service.chat(request("편안한 영화 90분 이내", session))
    # A node callback is bound at compile time; fail its downstream enrichment instead.
    def fail(_movie):
        raise RuntimeError("simulated failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "enrich", fail)
        with pytest.raises(RuntimeError):
            service.chat(request("150분 이내로 바꿔줘", session))
    result = service.chat(request("혼자 볼 거야", session))
    assert result.preferences.max_minutes == 90
