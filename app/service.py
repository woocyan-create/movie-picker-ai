import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import TypedDict

from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .catalog import MOVIES
from .config import Settings
from .imdb_data import GENRES, IMDbStore
from .models import ChatRequest, ChatResponse, Feedback, Preferences, Recommendation
from .prompts import CURATOR, RETRIEVER, analysis_messages
from .rag import MovieRAG


class State(TypedDict, total=False):
    request: dict
    preferences: dict
    history: list
    pool: list
    candidates: list
    chunks: list
    messages: list
    pending: list
    rounds: int
    tool_trace: list
    steps: list
    warnings: list
    result: dict
    search_requested: bool


class Pick(BaseModel):
    movie_id: str
    reason: str
    tip: str
    evidence_ids: list[str] = Field(min_length=1)


class Curation(BaseModel):
    message: str
    picks: list[Pick] = Field(min_length=1, max_length=2)


class SearchArgs(BaseModel):
    query: str = Field(max_length=200, description="Movie title or empty string for preference discovery")


class KnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1000, description="Viewing mood and genres for evidence retrieval")


class InspectArgs(BaseModel):
    movie_id: str = Field(max_length=50)


class MovieService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = Path(settings.data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.client = None
        self.chat_model, self.embedding_model = settings.openai_model, settings.embedding_model
        if settings.app_mode == "live":
            from openai import AzureOpenAI, OpenAI
            if settings.llm_provider == "azure":
                if not all([settings.aoai_api_key, settings.aoai_endpoint, settings.aoai_deploy_gpt41_mini, settings.aoai_deploy_embed_3_small]):
                    raise ValueError("Azure 모드에는 AOAI_ENDPOINT, AOAI_API_KEY, 채팅·임베딩 배포명이 필요합니다.")
                self.client = AzureOpenAI(api_key=settings.aoai_api_key, azure_endpoint=settings.aoai_endpoint, api_version=settings.azure_api_version, timeout=45, max_retries=1)
                self.chat_model, self.embedding_model = settings.aoai_deploy_gpt41_mini, settings.aoai_deploy_embed_3_small
            else:
                if not settings.openai_api_key:
                    raise ValueError("Live 모드에는 OPENAI_API_KEY가 필요합니다.")
                self.client = OpenAI(api_key=settings.openai_api_key, timeout=45, max_retries=1)
        self.imdb = IMDbStore(self.root)
        self.rag = MovieRAG(self.root, self.client, self.embedding_model, settings.llm_provider)
        with self.db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS feedback (session TEXT, movie TEXT, rating INTEGER, comment TEXT, mood_change INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.memory_connection = sqlite3.connect(self.root / "conversations.sqlite3", check_same_thread=False)
        self.checkpointer = SqliteSaver(self.memory_connection)
        graph = StateGraph(State)
        graph.add_node("EmotionAnalyzerAgent", self.analyze)
        graph.add_node("MovieRetrieverAgent", self.plan)
        graph.add_node("Tools", self.execute_tools)
        graph.add_node("CuratorAgent", self.curate)
        graph.add_edge(START, "EmotionAnalyzerAgent")
        graph.add_conditional_edges("EmotionAnalyzerAgent", lambda s: "search" if self.can_recommend(s) else "ask", {"search": "MovieRetrieverAgent", "ask": "CuratorAgent"})
        graph.add_conditional_edges("MovieRetrieverAgent", lambda s: "act" if s["pending"] else "finish", {"act": "Tools", "finish": "CuratorAgent"})
        graph.add_edge("Tools", "MovieRetrieverAgent")
        graph.add_edge("CuratorAgent", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def close(self):
        self.memory_connection.close()
        if self.client:
            self.client.close()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root / "movie_picker.sqlite3")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def status(self):
        return self.imdb.status() if self.settings.movie_source == "imdb" else {"ready": True, "count": len(MOVIES)}

    def structured(self, schema, messages):
        response = self.client.chat.completions.parse(model=self.chat_model, messages=messages, response_format=schema)
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("AI가 유효한 구조화 응답을 반환하지 않았습니다.")
        return parsed

    def analyze(self, state):
        req = ChatRequest.model_validate(state["request"])
        previous = Preferences.model_validate(state.get("preferences", {}))
        history = state.get("history", [])[-10:]
        p, text = previous.model_copy(deep=True), req.message
        if self.client:
            p = self.structured(Preferences, analysis_messages(previous.model_dump(), text, history))
        else:
            groups = [("힐링", ["지친", "지쳐", "편안", "편하", "쉬고", "힐링", "잔잔", "피곤", "비가", "비도"]), ("스트레스", ["스트레스", "회사", "속상", "힘들", "화나"]), ("위로", ["우울", "외로", "슬퍼", "위로"]), ("웃음", ["웃", "코미디", "가볍"]), ("설렘", ["설레", "설렘", "데이트", "로맨스"]), ("몰입", ["몰입", "집중", "SF", "스릴러"]), ("통쾌함", ["통쾌", "액션"]), ("기쁨", ["기뻐", "기쁜", "행복"])]
            for mood, words in groups:
                if any(bool(re.search(r"(?<!영)화나", text)) if w == "화나" else w in text for w in words):
                    p.mood = mood
                    break
            found = []
            for genre in GENRES.values():
                if genre in text:
                    if re.search(re.escape(genre) + r"[^.!?\n]{0,12}(싫|말고|빼|제외|않)", text):
                        p.avoid = sorted(set(p.avoid + [genre]))
                    else:
                        found.append(genre)
            if found:
                p.genres = found
            if "장르 상관없" in text:
                p.genres = []
            match = re.search(r"(\d+)\s*분", text)
            hours = re.search(r"(\d+)\s*시간(?:\s*(반|\d+\s*분))?", text)
            if hours:
                tail = hours.group(2) or ""
                p.max_minutes = min(600, max(1, int(hours.group(1)) * 60 + (30 if tail == "반" else int(re.sub(r"\D", "", tail) or 0))))
            elif match:
                p.max_minutes = min(600, max(1, int(match.group(1))))
            if "시간 상관없" in text:
                p.max_minutes = None
            if "혼자" in text:
                p.company = "혼자"
            elif any(w in text for w in ["함께", "친구", "연인", "가족"]):
                p.company = "함께"
            title = re.search(r'["“](.+?)["”]', text)
            if title:
                p.title_query = title.group(1)[:200]
            imdb_id = re.search(r"\btt\d{5,12}\b", text)
            if imdb_id:
                p.title_query = imdb_id.group()
        if req.max_minutes is not None:
            p.max_minutes = req.max_minutes
        search_requested = bool(re.search(r"(영화|작품).*(추천|찾|찯|골라|검색|보여)|(추천|찾|찯|골라|검색).*(영화|작품)|^\s*(추천해\s*줘|추천해\s*주세요|추천해주세요|아무거나|아무\s*영화)", text))
        return {"preferences": p.model_dump(), "search_requested": search_requested, "history": history, "pool": [], "candidates": [], "chunks": [], "rounds": 0, "pending": [], "tool_trace": [], "warnings": [],
                "messages": [{"role": "system", "content": RETRIEVER}, {"role": "user", "content": json.dumps({"message": text, "preferences": p.model_dump(), "history": history}, ensure_ascii=False)}],
                "steps": ["감정·조건 분석 및 SQLite 대화 메모리 조회"]}

    @staticmethod
    def can_recommend(state):
        p = state["preferences"]
        return bool(state.get("search_requested") or p["mood"] or p["genres"] or p["title_query"] or p.get("max_minutes") or p.get("avoid"))

    @staticmethod
    def matches(movie, p):
        return (not p.max_minutes or movie.get("runtime") is not None and movie["runtime"] <= p.max_minutes) and not set(movie["genres"]) & set(p.avoid) and (not p.genres or bool(set(movie["genres"]) & set(p.genres)))

    def make_tools(self, state):
        p = Preferences.model_validate(state["preferences"])

        def search_imdb(query: str):
            """Search official IMDb data using immutable viewing constraints."""
            query = query or p.title_query
            if self.settings.movie_source == "imdb":
                if re.fullmatch(r"tt\d+", query):
                    movie = self.imdb.get(query)
                    pool = [movie] if movie and self.matches(movie, p) else []
                else:
                    pool = self.imdb.search(query, p, self.settings.rag_pool_size)
            else:
                pool = [{**m, "source": "자체 작성 샘플 카탈로그", "source_url": None} for m in MOVIES if self.matches(m, p) and (not query or query.casefold() in (m["title"] + " " + m["original"]).casefold())]
            state.update(pool=pool, candidates=[], chunks=[])
            return {"count": len(pool), "movies": [{k: m.get(k) for k in ("id", "title", "genres", "runtime", "rating", "source_url")} for m in pool[:10]], "source": self.settings.movie_source}

        def retrieve_knowledge(query: str):
            """Embed and retrieve source-labelled evidence chunks for current candidates."""
            if not state["pool"]:
                return {"count": 0, "message": "먼저 search_imdb로 후보를 확보하세요."}
            limit = 12 if self.client else min(240, len(state["pool"]) * 4)
            chunks = self.rag.retrieve(state["pool"], query, limit=limit)
            order = list(dict.fromkeys(c["movie_id"] for c in chunks))
            if not self.client:
                # Demo combines retrieved evidence with transparent metadata ranking.
                # An unspecified mood never blocks a direct request for recommendations.
                preferred = {"힐링": {"가족", "코미디", "애니메이션"}, "위로": {"가족", "드라마"}, "웃음": {"코미디"}, "스트레스": {"코미디", "모험"}, "몰입": {"SF", "미스터리", "스릴러"}, "설렘": {"로맨스"}, "통쾌함": {"액션", "모험"}}.get(p.mood, set())
                movies = {m["id"]: m for m in state["pool"]}
                order.sort(key=lambda mid: (len(set(movies[mid]["genres"]) & preferred), movies[mid].get("votes") or 0, movies[mid].get("rating") or 0), reverse=True)
            state.update(chunks=chunks, candidates=[next(m for m in state["pool"] if m["id"] == mid) for mid in order[:3]])
            return {"count": len(chunks), "chunks": chunks}

        def inspect_movie(movie_id: str):
            """Inspect verified metadata for an ID already returned by search_imdb."""
            movie = next((m for m in state["pool"] if m["id"] == movie_id), None)
            if movie is None:
                raise ValueError("현재 검색 후보에 없는 영화입니다.")
            return movie

        return {fn.__name__: StructuredTool.from_function(fn, args_schema=schema) for fn, schema in [(search_imdb, SearchArgs), (retrieve_knowledge, KnowledgeArgs), (inspect_movie, InspectArgs)]}

    def plan(self, state):
        if state["rounds"] >= max(1, min(self.settings.react_max_rounds, 10)):
            return {"pending": [], "warnings": state["warnings"] + ["도구 실행 한도에 도달하여 확보된 검색 근거로 마무리했습니다."]}
        messages = list(state["messages"])
        if self.client:
            specs = [{"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.args_schema.model_json_schema()}} for tool in self.make_tools(dict(state)).values()]
            choice = "auto"
            if not state["tool_trace"]:
                choice = {"type": "function", "function": {"name": "search_imdb"}}
            elif state["pool"] and not state["chunks"]:
                choice = {"type": "function", "function": {"name": "retrieve_knowledge"}}
            response = self.client.chat.completions.create(model=self.chat_model, messages=messages, tools=specs, tool_choice=choice, parallel_tool_calls=False)
            answer = response.choices[0].message
            pending = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in answer.tool_calls or []]
            message = {"role": "assistant", "content": answer.content}
            if pending:
                message["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in pending]
            messages.append(message)
        else:
            p = Preferences.model_validate(state["preferences"])
            if not state["tool_trace"]:
                name, args = "search_imdb", {"query": p.title_query}
            elif not state["pool"] or any(e["tool"] == "retrieve_knowledge" for e in state["tool_trace"]):
                return {"pending": []}
            else:
                related = {"힐링": "가족 Family 드라마 Drama", "웃음": "코미디 Comedy", "위로": "드라마 Drama 가족 Family", "몰입": "SF Sci-Fi 스릴러 Thriller", "설렘": "로맨스 Romance", "스트레스": "코미디 Comedy", "통쾌함": "액션 Action"}
                name, args = "retrieve_knowledge", {"query": " ".join([state["request"]["message"], p.mood, *p.genres, related.get(p.mood, "")])[:1000]}
            pending = [{"id": f"demo-{state['rounds']}", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}]
            messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": pending[0]["id"], "type": "function", "function": {"name": name, "arguments": pending[0]["arguments"]}}]})
        return {"pending": pending, "messages": messages, "rounds": state["rounds"] + 1}

    def execute_tools(self, state):
        working = {**state, "pool": list(state["pool"]), "chunks": list(state["chunks"]), "candidates": list(state["candidates"])}
        tools = self.make_tools(working)
        trace, warnings, messages = list(state["tool_trace"]), list(state["warnings"]), list(state["messages"])
        for call in state["pending"]:
            try:
                if call["name"] not in tools:
                    raise ValueError("허용되지 않은 도구입니다.")
                output = tools[call["name"]].invoke(json.loads(call["arguments"]))
                event = {"tool": call["name"], "status": "ok", "count": output.get("count", 1)}
            except (ValueError, TypeError, FileNotFoundError) as exc:
                output, event = {"error": str(exc)}, {"tool": call["name"], "status": "error", "count": 0}
                warnings.append(str(exc))
            trace.append(event)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output, ensure_ascii=False)})
        return {"pool": working["pool"], "chunks": working["chunks"], "candidates": working["candidates"], "tool_trace": trace, "messages": messages, "pending": [], "warnings": list(dict.fromkeys(warnings))}

    def curate(self, state):
        p = Preferences.model_validate(state["preferences"])
        candidates, chunks, picks = state["candidates"], state["chunks"], []
        if not self.can_recommend(state):
            message = "오늘은 편안하게 쉬고 싶으세요, 가볍게 웃고 싶으세요, 아니면 이야기에 푹 빠지고 싶으세요? 찾는 작품 이름을 알려주셔도 좋아요."
        elif not candidates:
            message = "검색 근거를 갖춘 후보를 찾지 못했어요. IMDb 데이터 준비 상태를 확인하거나 제목·시간·장르 조건을 바꿔보세요."
        elif self.client:
            result = self.structured(Curation, [{"role": "system", "content": CURATOR}, {"role": "user", "content": json.dumps({"preferences": p.model_dump(), "candidates": candidates, "evidence_chunks": chunks}, ensure_ascii=False)}])
            picks, message = result.picks, result.message
        else:
            message = "IMDb에서 관람 조건에 맞는 영화를 골랐어요. 마음에 드는 장르나 기분을 알려주시면 다음 추천에 반영할게요."
            picks = [Pick(movie_id=m["id"], reason=f"{', '.join(m['genres'])} 장르의 작품으로 관람 조건에 맞습니다. {m['note']}", tip="편안한 자리를 준비하고 집중할 시간을 확보해 보세요.", evidence_ids=[c["id"] for c in chunks if c["movie_id"] == m["id"]][:2]) for m in candidates[:2]]
        recommendations, seen = [], set()
        for pick in picks:
            movie = next((m for m in candidates if m["id"] == pick.movie_id), None)
            allowed = {c["id"]: c for c in chunks if c["movie_id"] == pick.movie_id}
            if movie is None or pick.movie_id in seen or not self.matches(movie, p) or not pick.evidence_ids or any(cid not in allowed for cid in pick.evidence_ids):
                raise ValueError("추천 영화 또는 인용 근거가 검색 결과와 일치하지 않습니다.")
            seen.add(pick.movie_id)
            recommendations.append(Recommendation(movie_id=movie["id"], title=movie["title"], year=movie.get("year"), runtime=movie.get("runtime"), genres=movie["genres"], synopsis=movie["synopsis"], reason=pick.reason, tip=pick.tip, evidence="\n".join(allowed[cid]["text"] for cid in pick.evidence_ids), evidence_chunks=pick.evidence_ids, rating=movie.get("rating"), votes=movie.get("votes"), source=movie["source"], source_url=movie.get("source_url")))
        steps = state["steps"] + [f"ReAct: {e['tool']} → {e['status']} ({e['count']})" for e in state["tool_trace"]] + ["청크 인용·제약 검증 및 큐레이션 완료"]
        response = ChatResponse(session_id=state["request"]["session_id"], mode=self.settings.app_mode, source=self.settings.movie_source, message=message, preferences=p, recommendations=recommendations, steps=steps, warnings=state["warnings"], tool_trace=state["tool_trace"])
        history = (state["history"] + [{"role": "user", "content": state["request"]["message"]}, {"role": "assistant", "content": message}])[-10:]
        return {"result": response.model_dump(mode="json"), "history": history, "messages": [], "pending": [], "pool": []}

    def chat(self, request: ChatRequest):
        with self.lock:
            config = {"configurable": {"thread_id": str(request.session_id)}}
            previous = self.graph.get_state(config)
            try:
                state = self.graph.invoke({"request": request.model_dump(mode="json")}, {**config, "recursion_limit": 40})
            except Exception:
                self.checkpointer.delete_thread(str(request.session_id))
                if previous.values:
                    self.graph.update_state(config, previous.values, as_node="CuratorAgent")
                raise
            return ChatResponse.model_validate(state["result"])

    def feedback(self, feedback: Feedback):
        known = self.imdb.get(feedback.movie_id) if self.settings.movie_source == "imdb" else next((m for m in MOVIES if m["id"] == feedback.movie_id), None)
        if known is None:
            raise ValueError("알 수 없는 영화입니다.")
        with self.db() as conn:
            conn.execute("INSERT INTO feedback(session,movie,rating,comment,mood_change) VALUES(?,?,?,?,?)", (str(feedback.session_id), feedback.movie_id, feedback.rating, feedback.comment, feedback.mood_change))
