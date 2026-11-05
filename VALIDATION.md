# 검증 기록

## 2026-11-05 데모 추천 보완

- 자동 테스트 21개 통과. 취향 없는 일반 추천·검색 요청 5종, 이전 시간 조건 유지, 화면의 일반 검색·경고 미표시를 추가 검증했습니다.
- 실제 IMDb 10,000편 DB에 일반 추천 요청 3종과 90분 이내 코미디 요청을 보내, 경고 없이 영화·IMDb 링크·근거 청크가 반환되는 것을 확인했습니다.
- Live API 검증 한계는 아래 기존 기록과 동일합니다. 이번 변경은 API 키 없는 데모 추천을 보완한 것입니다.

2026-11-04 / Windows / Python 3.12.10

## 완료

- Python 문법 검사, `pip check` 통과.
- 자동 테스트 15개 통과. 합성 TSV 정제·결측값·성인/시리즈 제외·SQL 안전성·제약 조건·인용·캐시·요청 간 검색 격리·디스크 메모리·실패 복구·모의 LLM Function Calling·관찰 기반 재시도·도구 허용 목록·반복 한도·잘못된 인용 거부·FastAPI·Streamlit 동작을 검증합니다.
- 공식 IMDb `title.basics.tsv.gz`와 `title.ratings.tsv.gz`를 실제 다운로드하고 비성인 영화 10,000편의 로컬 검색 DB를 구축했습니다.
- 실제 IMDb 데이터의 데모 검색·Chroma 청크 검색·추천·IMDb 링크·근거 ID를 확인했습니다. API 키 없는 데모 벡터는 어휘 해시이며 학습된 의미 임베딩이라고 표시하지 않습니다.

## Live 검증 한계

- 기존 `.env`에 설정된 Azure OpenAI로 실제 Live 요청을 시도했으나 HTTP 403(PermissionDeniedError)을 반환했습니다. 실제 Azure 분석·임베딩·생성은 검증 완료로 간주하지 않습니다. 접근 정책과 자격 증명 확인이 필요합니다.
- 실제 모델 대신 제어 가능한 모의 응답을 사용하는 통합 테스트에서 Function Calling → 도구 결과 관찰 → 재검색 → 청크 검색 → 큐레이션 흐름을 확인했습니다.
- OpenAI 직접 연결 키는 설정되지 않아 실제 외부 OpenAI 호출은 수행하지 않았습니다.
- Docker 실행 파일이 없어 컨테이너 빌드·실행은 미검증입니다.

## 결과물

- [자동 테스트 출력](docs/test-results.txt)
- [실제 IMDb 데모 응답](docs/sample-response.json)
- [Live 시도 결과](docs/live-validation.json)
- [홈 화면](docs/demo-home.png) / [추천 화면](docs/demo-recommendation.png)
- [패키지 버전](docs/tested-versions.txt)

원본 IMDb 데이터와 파생 DB·인덱스는 Git/ZIP에 포함하지 않습니다. 사용 환경에서 공식 다운로드 스크립트로 준비합니다. 코드·환경 템플릿·테스트에는 실제 API 키를 포함하지 않습니다.
