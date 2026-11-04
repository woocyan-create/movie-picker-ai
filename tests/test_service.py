import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.config import Settings
from app.imdb_data import IMDbStore, build_database
from app.models import ChatRequest, Feedback, Preferences
from app.rag import chunk_document
from app.service import Curation, MovieService, Pick


@pytest.fixture
def service(imdb_directory):
    instance = MovieService(Settings(app_mode="demo", movie_source="imdb", data_dir=str(imdb_directory)))
    yield instance
    instance.close()


def request(message, session=None, **kwargs):
    return ChatRequest(session_id=session or uuid4(), message=message, **kwargs)


def test_import_cleaning_and_null_runtime(imdb_directory):
    store = IMDbStore(imdb_directory)
    assert store.status()["count"] == 5
    movies = store.search("", Preferences(max_minutes=100))
    assert all(m["runtime"] is not None and m["runtime"] <= 100 for m in movies)
    assert store.get("tt0000005") is None
    assert store.get("tt0000006") is None
    assert store.get("tt0000001")["source_url"] == "https://www.imdb.com/title/tt0000001/"


def test_title_and_wildcard_search(imdb_directory):
    store = IMDbStore(imdb_directory)
    assert len(store.search("Quiet Fields", Preferences())) == 1
    assert store.search("%", Preferences()) == []
    assert store.search("' OR 1=1 --", Preferences()) == []


def test_pipeline_strict_filters_and_citations(service):
    result = service.chat(request("지쳐서 편안한 가족 영화 100분 이내"))
    assert len(result.recommendations) == 1
    movie = result.recommendations[0]
    assert movie.movie_id == "tt0000001"
    assert movie.runtime <= 100
    assert movie.source_url.endswith("/tt0000001/")
    assert movie.evidence_chunks
    assert all(cid.startswith(movie.movie_id + ":") for cid in movie.evidence_chunks)
    assert [e["tool"] for e in result.tool_trace] == ["search_imdb", "retrieve_knowledge"]


def test_memory_persists_across_restart(service):
    session = uuid4()
    service.chat(request("편안한 영화 90분 이내", session))
    other = MovieService(service.settings)
    try:
        result = other.chat(request("혼자 볼 거야", session))
        assert result.preferences.max_minutes == 90
        assert result.preferences.mood == "힐링"
        assert all(m.runtime <= 90 for m in result.recommendations)
        independent = other.chat(request("혼자 볼 거야"))
        assert not independent.recommendations
    finally:
        other.close()


def test_no_results_and_excluded_genre(service):
    assert not service.chat(request("웃고 싶어", max_minutes=10)).recommendations
    result = service.chat(request("몰입하고 싶어. 액션은 싫어. 2시간 반 이내"))
    assert result.preferences.max_minutes == 150
    assert "액션" in result.preferences.avoid
    assert all("액션" not in m.genres for m in result.recommendations)


def test_title_lookup_without_mood(service):
    result = service.chat(request('"Quiet Fields" 찾아줘'))
    assert result.recommendations[0].movie_id == "tt0000001"


def test_feedback_and_blank_input(service):
    feedback = Feedback(session_id=uuid4(), movie_id="tt0000001", rating=5, comment="좋았어요")
    service.feedback(feedback)
    with service.db() as conn:
        assert conn.execute("SELECT rating,comment FROM feedback").fetchone() == (5, "좋았어요")
    with pytest.raises(ValueError):
        service.feedback(feedback.model_copy(update={"movie_id": "unknown"}))
    with pytest.raises(ValidationError):
        request("  ")


def test_failed_turn_rolls_back(service, monkeypatch):
    session = uuid4()
    service.chat(request("편안한 영화 90분 이내", session))
    def fail(*args):
        raise RuntimeError("simulated embedding outage")
    with monkeypatch.context() as patch:
        patch.setattr(service.rag, "retrieve", fail)
        with pytest.raises(RuntimeError):
            service.chat(request("150분 이내로 바꿔줘", session))
    assert service.chat(request("혼자 볼 거야", session)).preferences.max_minutes == 90


def test_rag_chunk_cache_and_candidate_isolation(service, monkeypatch):
    first, second = service.imdb.get("tt0000001"), service.imdb.get("tt0000002")
    first["note"] = "A" * 1000
    assert len(chunk_document(first)) > 1
    calls = []
    original = service.rag.embed
    monkeypatch.setattr(service.rag, "embed", lambda texts: (calls.append(len(texts)) or original(texts)))
    service.rag.retrieve([first], "family")
    calls.clear()
    service.rag.retrieve([first], "family")
    assert calls == [1]  # cached documents; only query is embedded
    chunks = service.rag.retrieve([second], "comedy")
    assert all(c["movie_id"] == second["id"] for c in chunks)
    second["note"] = "A revised source note"
    updated = service.rag.retrieve([second], "comedy")
    allowed = {c["id"] for c in chunk_document(second)}
    assert all(c["id"] in allowed for c in updated)


def test_real_function_call_loop_with_fake_model(service, monkeypatch):
    """Exercise LLM tool-call dispatch, observation-driven retry and grounded curation."""
    rounds = []
    def create(**kwargs):
        rounds.append(kwargs["messages"])
        index = len(rounds)
        name = "search_imdb" if index <= 2 else "retrieve_knowledge"
        args = {"query": "does not exist" if index == 1 else "" if index == 2 else "코미디 Comedy"}
        calls = [SimpleNamespace(id=f"c{index}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))] if index <= 3 else []
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=calls, content=None))])
    service.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    def structured(schema, messages):
        if schema is Preferences:
            return Preferences(mood="웃음", genres=["코미디"], max_minutes=100)
        payload = json.loads(messages[-1]["content"])
        candidate = payload["candidates"][0]
        evidence = next(c for c in payload["evidence_chunks"] if c["movie_id"] == candidate["id"])
        return Curation(message="추천했어요", picks=[Pick(movie_id=candidate["id"], reason="코미디 장르와 시간 조건 일치", tip="편안하게 감상하세요", evidence_ids=[evidence["id"]])])
    monkeypatch.setattr(service, "structured", structured)
    result = service.chat(request("100분 안에 코미디를 보고 싶어"))
    assert result.recommendations
    assert [e["count"] for e in result.tool_trace][:2] == [0, 1]
    assert any(m["role"] == "tool" for m in rounds[-1])
    assert len(rounds) == 4


def test_invalid_tool_and_limit(service):
    state = service.analyze({"request": request("웃고 싶어").model_dump(mode="json")})
    state["pending"] = [{"id": "bad", "name": "run_shell", "arguments": "{}"}]
    observed = service.execute_tools(state)
    assert observed["tool_trace"][0]["status"] == "error"
    state["rounds"] = 99
    assert not service.plan(state)["pending"]


def test_fabricated_citation_rejected(service, monkeypatch):
    result = service.chat(request("편안한 영화"))
    session = str(result.session_id)
    state = service.graph.get_state({"configurable": {"thread_id": session}}).values
    service.client = SimpleNamespace(close=lambda: None)
    fake = Curation(message="test", picks=[Pick(movie_id=state["candidates"][0]["id"], reason="test", tip="test", evidence_ids=["fake-id"])])
    monkeypatch.setattr(service, "structured", lambda *args: fake)
    with pytest.raises(ValueError, match="인용 근거"):
        service.curate(state)


def test_api_contract(imdb_directory, monkeypatch):
    from app.api import app
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("MOVIE_SOURCE", "imdb")
    monkeypatch.setenv("DATA_DIR", str(imdb_directory))
    with TestClient(app) as client:
        assert client.get("/health").json()["dataset"]["count"] == 5
        result = client.post("/chat", json={"session_id": str(uuid4()), "message": "가볍게 웃고 싶어"})
        assert result.status_code == 200
        assert result.json()["recommendations"]
        assert client.post("/chat", json={"session_id": "invalid", "message": "hi"}).status_code == 422


def test_missing_dataset_is_visible(tmp_path):
    service = MovieService(Settings(app_mode="demo", movie_source="imdb", data_dir=str(tmp_path)))
    try:
        result = service.chat(request("웃고 싶어"))
        assert not result.recommendations
        assert any("import_imdb" in warning for warning in result.warnings)
    finally:
        service.close()
