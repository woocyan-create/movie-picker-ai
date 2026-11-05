import os
from uuid import uuid4

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
st.set_page_config(page_title="Movie Picker · 오늘의 마음에 맞는 영화", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp {background: #101014; color: #ece9f5;}
[data-testid="stSidebar"] {background: #18171f; border-right: 1px solid #302c3c;}
.block-container {max-width: 1160px; padding-top: 2.4rem;}
h1 {font-size: clamp(2rem, 4vw, 3.5rem)!important; letter-spacing: -.06em; font-weight: 750!important;}
h2,h3 {letter-spacing: -.03em;}
.eyebrow {color: #b8a1f5; font-size: .78rem; letter-spacing: .2em; margin-bottom: 1rem;}
.intro {color: #aaa5b8; font-size: 1.05rem; line-height: 1.8; margin-bottom: 2rem;}
.highlight {color: #c5adff;}
.brand {font-size: 1.5rem; font-weight: 750; letter-spacing: -.05em; margin-bottom: .4rem;}
.small-label {color: #aaa5b8; font-size: .75rem; letter-spacing: .1em;}
.poster-placeholder {background: linear-gradient(155deg,#38304d,#252c37 55%,#16171e); min-height: 230px; border-radius: 12px; display: flex; align-items:center; justify-content:center; font-size: 4rem; margin-bottom: 1rem;}
[data-testid="stChatMessage"] {background: #1b1923; border: 1px solid #302b3d; border-radius: 16px;}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius: 16px!important;}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"] {background:#b89aee; color:#17111f; border:0;}
div[data-testid="stBottom"]>div {background: #101014;}
</style>""", unsafe_allow_html=True)

if st.session_state.get("schema_version") != 3:
    st.session_state.schema_version = 3
    st.session_state.session_id = str(uuid4())
    st.session_state.messages = []


def render_result(result, turn):
    st.write(result["message"])
    prefs = result["preferences"]
    tags = [prefs["mood"], *prefs["genres"], prefs["company"]]
    if prefs.get("max_minutes"):
        tags.append(f"{prefs['max_minutes']}분 이내")
    if prefs.get("title_query"):
        tags.append(prefs["title_query"])
    if any(tags):
        st.caption("  ·  ".join(t for t in tags if t))
    for warning in result["warnings"]:
        st.warning(warning)
    movies = result["recommendations"]
    if movies:
        for col, movie in zip(st.columns(len(movies)), movies):
            with col, st.container(border=True):
                if movie.get("poster"):
                    st.image(movie["poster"], width=260)
                else:
                    st.markdown('<div class="poster-placeholder">🎞</div>', unsafe_allow_html=True)
                st.caption(f"{movie['year'] or '연도 미상'}  /  {' · '.join(movie['genres'])}  /  {str(movie['runtime']) + '분' if movie['runtime'] else '상영 시간 미상'}")
                st.subheader(movie["title"])
                if movie.get("rating") is not None:
                    st.caption(f"IMDb 평점 {movie['rating']:.1f} / 10 · {movie.get('votes') or 0:,}표")
                st.write(movie["synopsis"])
                st.markdown("**지금 이 영화인 이유**")
                st.write(movie["reason"])
                st.info("감상 팁 · " + movie["tip"])
                st.caption(movie["source"])
                if movie.get("source_url"):
                    st.link_button("IMDb에서 작품 보기 ↗", movie["source_url"])
                with st.expander("추천 근거 보기"):
                    st.write(movie["evidence"])
                    st.caption("인용 청크: " + " · ".join(movie.get("evidence_chunks", [])))
                    st.caption("IMDb 공식 데이터셋의 메타데이터 검색 결과입니다. 무료 데이터에는 줄거리·리뷰·포스터·스트리밍 제공처가 포함되지 않습니다.")
                with st.expander("이 영화, 어땠나요?"):
                    form_key = f"feedback-{turn}-{movie['movie_id']}"
                    with st.form(form_key):
                        rating = st.slider("나의 별점", 1, 5, 4)
                        mood_change = st.slider("보기 전보다 기분이 좋아졌나요?", -5, 5, 0)
                        comment = st.text_input("한 줄 감상", max_chars=1000, placeholder="마음에 남은 장면을 알려주세요")
                        submitted = st.form_submit_button("감상 저장")
                    if submitted:
                        try:
                            response = httpx.post(f"{API_URL}/feedback", json={"session_id": str(result["session_id"]), "movie_id": movie["movie_id"], "rating": rating, "mood_change": mood_change, "comment": comment}, timeout=10)
                            response.raise_for_status()
                            st.success("감상을 저장했어요.")
                        except httpx.HTTPError:
                            st.error("감상을 저장하지 못했어요. 서버 연결을 확인해 주세요.")
    with st.expander("큐레이션 과정"):
        for i, step in enumerate(result["steps"], 1):
            st.write(f"{i}. {step}")


with st.sidebar:
    st.markdown('<div class="brand">◈ Movie Picker</div>', unsafe_allow_html=True)
    st.caption("당신의 하루에, 영화 한 편")
    st.divider()
    if st.button("＋ 새로운 영화 이야기", use_container_width=True):
        st.session_state.session_id = str(uuid4())
        st.session_state.messages = []
        st.rerun()
    st.markdown("### 오늘의 관람 조건")
    time_limit = st.select_slider("얼마나 여유가 있나요?", options=["상관없음", "90분", "120분", "150분", "180분"], value="상관없음")
    st.caption("IMDb 영화 데이터에서 찾아드려요. OTT 선택은 필요하지 않습니다. 대화 조건을 초기화하려면 새 이야기를 시작하세요.")
    st.divider()
    try:
        health = httpx.get(f"{API_URL}/health", timeout=2)
        health.raise_for_status()
        status = health.json()
        mode = status["mode"]
        st.caption("● DEMO · API 키 없이 영화 추천" if mode == "demo" else "● LIVE · AI 큐레이션")
        dataset = status.get("dataset", {})
        source_label = "IMDb" if status.get("source") == "imdb" else "샘플 카탈로그"
        st.caption(f"{source_label} · {dataset.get('count', 0):,}편")
        if not dataset.get("ready", True):
            st.warning("IMDb 데이터를 먼저 준비해 주세요.")
            st.code("python -m scripts.import_imdb", language="bash")
    except (httpx.HTTPError, ValueError, KeyError):
        st.caption("○ 추천 서버 연결 대기")
    with st.expander("추천 방식 안내"):
        st.caption("데모에서도 IMDb 영화 추천을 사용할 수 있어요. 장르·시간·투표 수와 검색 근거를 활용합니다. Live는 LLM 도구 선택과 의미 임베딩을 추가로 사용합니다.")
    st.caption("감상평과 세션별 대화 맥락은 로컬 DB에 저장됩니다.")

st.markdown('<div class="eyebrow">A LITTLE CINEMA, JUST FOR YOU</div>', unsafe_allow_html=True)
st.markdown('<h1>오늘의 마음에,<br><span class="highlight">딱 맞는 영화.</span></h1>', unsafe_allow_html=True)
st.markdown('<div class="intro">고르는 시간은 짧게, 여운은 길게.<br>지금의 기분을 들려주면 함께 볼 영화를 찾아드릴게요.</div>', unsafe_allow_html=True)

quick_prompt = None
if not st.session_state.messages:
    st.caption("이런 이야기로 시작해 보세요")
    examples = ["☁️ 지친 하루의 끝", "🍿 가볍게 웃고 싶어", "✨ 이야기에 푹 빠지기"]
    texts = ["오늘 회사에서 힘들었어. 혼자 편안하게 쉬면서 볼 영화 추천해줘.", "친구와 함께 가볍게 웃을 수 있는 코미디가 보고 싶어.", "현실을 잊고 몰입할 수 있는 SF 영화를 추천해줘."]
    for col, label, text in zip(st.columns(3), examples, texts):
        if col.button(label, use_container_width=True):
            quick_prompt = text

for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"], avatar="🎬" if message["role"] == "assistant" else None):
        if message["role"] == "user":
            st.write(message["content"])
        else:
            render_result(message["content"], i)

prompt = st.chat_input("오늘은 어떤 하루였나요? 기분이나 보고 싶은 영화를 이야기해 주세요.", max_chars=3000)
prompt = prompt or quick_prompt
if prompt:
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant", avatar="🎬"):
        with st.spinner("당신의 마음에 어울리는 영화를 고르고 있어요…"):
            try:
                response = httpx.post(f"{API_URL}/chat", json={"session_id": st.session_state.session_id, "message": prompt, "max_minutes": None if time_limit == "상관없음" else int(time_limit[:-1])}, timeout=300)
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, ValueError):
                st.error("추천을 가져오지 못했어요. FastAPI 서버 실행 상태와 API 설정을 확인한 뒤 다시 시도해 주세요.")
            else:
                st.session_state.messages.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": result}])
                st.rerun()

st.divider()
st.caption("MOVIE PICKER  /  마음을 듣고, 영화를 고릅니다.")
st.caption("영화 정보 출처: IMDb 공식 비상업용 데이터셋 · 개인·비상업적 학습용 · IMDb와 제휴하거나 인증받은 서비스가 아닙니다.")
