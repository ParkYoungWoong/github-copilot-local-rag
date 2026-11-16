# 로컬 RAG 시작 파일

문서 폴더를 내 PC에서 RAG(검색 증강 생성)로 만들고, 어느 프로젝트에서든 Copilot에게 말로 검색을 요청할 수 있게 하는 프롬프트 파일입니다.
[GitHub Copilot 업무 비서 만들기](https://www.heropy.dev/p/PgnSNw)의 '로컬 RAG'에서 사용합니다.
이 저장소를 받은 폴더(이하 `local-rag` 폴더)가 그대로 RAG 도구의 설치 폴더가 됩니다.

## 만들어지는 것

| 구성 요소 | 이름과 위치 | 하는 일 |
| --- | --- | --- |
| 개인 스킬 | `local-rag`, `~/.copilot/skills/local-rag/SKILL.md` | 말로 한 요청을 `rag` 명령으로 실행. `/local-rag`로 직접 호출할 수 있음 |
| `rag` 명령 | `local-rag` 폴더의 `bin/` | 폴더 색인, 검색, 갱신, 목록, 삭제 |
| 벡터 DB | `local-rag` 폴더의 `indexes/<컬렉션>.db` | RAG로 만든 폴더(컬렉션)마다 파일 하나 |
| 임베딩 모델 | Ollama의 `qwen3-embedding:0.6b` | 문서 조각과 질문을 벡터로 바꿈 |

## 사용 순서

준비물은 VS Code, GitHub Copilot, [Python](https://www.python.org/downloads/)입니다. Ollama는 `1-setup.md`에서 설치합니다.

1. 저장소 페이지에서 `Code > Download ZIP`을 눌러 압축 파일을 받고 압축을 풉니다. Git을 사용한다면 클론해도 됩니다.
1. VS Code의 `파일 > 폴더 열기`로 압축을 푼 폴더를 열고, 에이전트를 Agent로 둡니다.
1. 입력창에서 `#`을 입력해 `1-setup.md`를 첨부하고, "첨부한 파일의 내용대로 진행해 줘"라고 요청합니다.
1. 끝나면 같은 방법으로 `2-rag-tool.md`를 요청합니다.
1. VS Code를 완전히 종료했다가 다시 엽니다. 그래야 PATH에 추가한 `rag` 명령을 사용할 수 있습니다.
1. 같은 방법으로 `3-skill.md`를 요청합니다.
1. 다른 프로젝트를 열고 새 대화에서 `/`를 입력했을 때 `local-rag`가 보이면 준비가 끝난 것입니다.

| 파일 | 하는 일 | 실행 시점 |
| --- | --- | --- |
| `1-setup.md` | Python 가상 환경, sqlite-vec, Ollama와 모델 준비, 이 PC의 임베딩 속도 측정 | 처음 한 번 |
| `2-rag-tool.md` | `rag` 명령 만들기, 자체 시험, PATH 등록 | 처음 한 번 |
| `3-skill.md` | `local-rag` 스킬과 터미널 자동 승인 규칙 | 처음 한 번 |
| `4-check-quality.md` | 컬렉션 하나의 검색 품질 점검 | 필요할 때 |

## 사용 예

어느 프로젝트에서든 요청에 'RAG'를 넣어 말합니다. 스킬이 선택되지 않으면 요청 앞에 `/local-rag`를 붙입니다.

- docs 폴더 파일 모두를 RAG로 만들어 줘.
- RAG에서 TS-100의 동작 온도 범위를 찾아 줘.
- RAG 목록 보여 줘.
- RAG 갱신해 줘.
- docs 컬렉션 지워 줘.

문서가 바뀌면 원본 파일만 수정합니다. 검색할 때마다 바뀐 파일을 확인해서 그 파일만 다시 처리합니다.

## 주의

- 폴더는 OneDrive, iCloud Drive 같은 동기화 폴더나 다른 프로젝트 폴더 안에 두지 않습니다. `1-setup.md`가 위치를 먼저 확인합니다.
- 설치한 뒤에는 폴더를 옮기지 않습니다. 옮겼다면 Copilot에게 "local-rag 폴더를 옮겼으니 PATH와 스킬의 경로를 고쳐 줘"라고 요청합니다.

- 검색으로 찾은 조각은 Copilot 대화에 포함되어 GitHub의 서버로 전달됩니다. Copilot에 보내면 안 되는 문서는 RAG로 만들지 않습니다.
- 지금 구성은 `.md`, `.markdown`, `.txt` 파일만 읽습니다. Word나 PDF 문서는 마크다운으로 변환한 뒤 RAG로 만듭니다.
- `2-rag-tool.md`는 사용법을 `USAGE.md`에 정리합니다. 이 `README.md`는 덮어쓰지 않습니다.
