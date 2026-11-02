# 검증 기록

검증일: 2026-11-02 (Asia/Seoul). Windows / Python 3.12.10 환경.

## 수행한 검증

- Python 전체 소스 문법 검사 통과.
- pytest 10개 통과: 감정 기반 추천, 시간 제한, 대화 메모리·세션 분리, 조건 불일치, OTT 정보 미확인, 제외 장르, 피드백 영속 저장·입력 검증, FastAPI 계약, 제공처 이름 매칭, 실패한 대화의 상태 복구, Streamlit 화면 상호작용을 검증합니다. 일부 테스트에서 여러 항목을 함께 확인합니다.
- Streamlit AppTest에서 메시지 입력 → 실제 FastAPI 서비스 로직 → 추천 카드 2편 → 감상 저장 → 새 대화 초기화를 확인했습니다. 이 테스트의 HTTP 전송만 TestClient로 연결하며 추천 결과는 고정 응답으로 대체하지 않습니다.
- 실제 localhost 서버의 `/health`, Streamlit `/_stcore/health`, `/chat` 요청 성공을 확인했습니다.
- 실제 Chrome에서 시작 예시를 클릭하고 추천 결과가 표시된 후 화면을 캡처했습니다.
- `pip check`: No broken requirements found.

## 결과물

- [홈 실행 화면](docs/demo-home.png)
- [실제 추천 화면](docs/demo-recommendation.png)
- [시스템 구조도](docs/architecture.jpg)
- [서비스 흐름도](docs/flow.jpg)
- [테스트 출력](docs/test-results.txt)
- [실제 API 응답](docs/sample-response.json)
- [검증 패키지 버전](docs/tested-versions.txt)

## 미검증 및 남은 작업

- API 키를 제공받지 않아 실제 OpenAI 모델·임베딩 및 TMDB 외부 호출은 실행하지 않았습니다.
- Docker 실행 파일이 이 환경에 없어 컨테이너 빌드는 수행하지 않았습니다.
- GitHub 저장소: https://github.com/woocyan-create/movie-picker-ai. 소스 및 문서를 관리하며 비밀키와 실행 DB는 제외합니다.
- MCP 표준 서버, A2A 통신, 자동 개인화 학습, 선제 알림은 포함하지 않았습니다.

외부 SDK 구현 참고: [OpenAI 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [LangGraph 메모리](https://docs.langchain.com/oss/python/langgraph/add-memory), [Chroma 검색](https://docs.trychroma.com/docs/querying-collections/query-and-get).
