from pathlib import Path
import httpx
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest


def test_chat_cards_links_feedback_and_no_ott(imdb_directory, monkeypatch):
    from app.api import app
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("MOVIE_SOURCE", "imdb")
    monkeypatch.setenv("DATA_DIR", str(imdb_directory))
    with TestClient(app) as client:
        monkeypatch.setattr(httpx, "get", lambda url, **kw: client.get("/" + url.rsplit("/", 1)[-1]))
        monkeypatch.setattr(httpx, "post", lambda url, **kw: client.post("/" + url.rsplit("/", 1)[-1], json=kw["json"]))
        page = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=30).run()
        assert not page.exception
        assert not page.multiselect
        page.chat_input[0].set_value("편안한 가족 영화 100분 이내").run()
        assert not page.exception
        assert page.subheader[0].value == "Quiet Fields"
        assert page.get("link_button")[0].url.endswith("/tt0000001/")
        next(b for b in page.button if b.label == "감상 저장").click().run()
        assert not page.exception
        assert page.success[0].value == "감상을 저장했어요."
        next(b for b in page.button if "새로운 영화" in b.label).click().run()
        assert not page.chat_message
