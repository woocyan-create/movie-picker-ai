import httpx
from pathlib import Path
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest


def test_chat_cards_and_feedback(tmp_path, monkeypatch):
    from app.api import app
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("TMDB_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        monkeypatch.setattr(httpx, "get", lambda url, **kw: client.get("/" + url.rsplit("/", 1)[-1]))
        monkeypatch.setattr(httpx, "post", lambda url, **kw: client.post("/" + url.rsplit("/", 1)[-1], json=kw["json"]))
        page = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=20).run()
        assert not page.exception
        page.chat_input[0].set_value("지쳐서 편안한 영화 추천해줘").run()
        assert not page.exception
        assert len(page.chat_message) == 2
        assert len(page.subheader) == 2
        assert any("리틀 포레스트" in h.value for h in page.subheader)
        save = next(button for button in page.button if button.label == "감상 저장")
        save.click().run()
        assert not page.exception
        assert page.success[0].value == "감상을 저장했어요."
        with app.state.service.db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1
        next(button for button in page.button if "새로운 영화" in button.label).click().run()
        assert not page.chat_message
