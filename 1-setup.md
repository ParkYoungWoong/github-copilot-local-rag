# 1단계: 환경 준비

이 폴더(`local-rag`)를 여러 프로젝트에서 같이 쓸 로컬 RAG 환경의 설치 폴더로 쓸 거야.
이번에는 환경만 준비하고, 검색 도구 코드는 만들지 마.

## 확인할 것

0. 이 폴더의 위치를 확인해. OneDrive, iCloud Drive, Dropbox 같은 동기화 폴더 안이거나, 이 폴더 바깥의 다른 Git 저장소 안에 들어 있으면 이유와 함께 알려 줘. 내가 확인하면 홈 폴더 아래 같은 이름의 폴더로 복사하고, VS Code의 `파일 > 폴더 열기`로 그 폴더를 다시 연 뒤 이 파일을 다시 요청하라고 안내하고 멈춰.
1. 운영체제, CPU 종류, 디스크 여유 공간, Python 버전, Python이 쓰는 SQLite 버전을 확인해.
   - Python이 없거나, Windows에서 `python`이 Microsoft Store 바로 가기로만 열리면, python.org 설치 파일로 설치하라고 안내하고 멈춰.
   - Python의 `sqlite3`가 확장 불러오기(`enable_load_extension`)를 지원하지 않으면, 지원하는 Python 설치 방법을 알려 주고 멈춰. macOS 기본 Python은 지원하지 않고, python.org의 Windows용 Python은 지원해.
   - sqlite-vec는 Windows x64, macOS(Intel, Apple Silicon), Linux(x64, ARM64)용만 있어. 그 밖의 환경(Windows ARM 등)이면 알려 주고 멈춰.
   - Ollama를 새로 설치해야 하면 디스크 여유 공간이 8GB 이상인지 확인해. Windows 기준으로 설치 파일 약 1.9GB, 설치 공간 약 4GB, 모델 약 0.6GB가 필요해.

## 설치할 것

2. 이 폴더에 `.venv` 가상 환경을 만들고 sqlite-vec를 설치해. `--pre` 없이 정식 버전으로 설치하고, 설치한 버전은 `requirements.txt`에 고정해 줘.
3. Ollama가 설치되어 있는지 확인해. 없으면 내 확인을 받고 공식 설치 스크립트로 설치해.
   - Windows: `irm https://ollama.com/install.ps1 | iex` (관리자 권한 필요 없음)
   - macOS/Linux: `curl -fsSL https://ollama.com/install.sh | sh`
   - 비밀번호(sudo)를 묻는 설치는 직접 실행하지 말고, 내가 터미널에서 실행할 명령만 알려 줘.
   - 스크립트가 막히면 https://ollama.com/download 에서 설치 파일을 받아 내가 직접 설치하도록 안내해.
   - 설치 직후에는 터미널에 PATH가 반영되지 않았을 수 있어. `ollama`를 찾지 못하면 설치 경로의 전체 경로로 실행해(Windows: `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`).
4. Ollama가 `http://127.0.0.1:11434`에서 응답하는지 확인해. 응답이 없으면 터미널에서 `ollama serve`를 실행하지 말고, Ollama 앱을 실행하라고 안내해(Windows는 시작 메뉴, macOS는 `open -a Ollama`).
5. `qwen3-embedding:0.6b` 모델이 없으면 `ollama pull`로 받아. 태그 없는 `qwen3-embedding`은 8B 모델(4.7GB)이라 받지 마.

## 설정 파일

6. `config.json`을 만들어 줘. 항목은 다음과 같아.
   - `embed_model`: `"qwen3-embedding:0.6b"`
   - `ollama_url`: `"http://127.0.0.1:11434"`
   - `num_ctx`: `4096` (모델이 쓰는 메모리를 정하는 값이라, 모든 호출에 같은 값을 넣어야 해)
   - `keep_alive`: `"30m"`
   - `query_instruction`: `"Given a question, retrieve passages from internal documents that answer the question"`
   - `embed_chunks_per_sec`: 7번에서 잰 값

## 점검

7. `check_env.py`를 만들어서 `.venv`의 Python으로 실행해 줘.
   - Ollama 호출은 회사 프록시 환경 변수를 타지 않게 urllib의 `ProxyHandler({})`로 해. 요청에는 `config.json`의 `keep_alive`를, `options`에는 `num_ctx`를 넣어.
   - 한글 문장 하나를 `/api/embed`로 임베딩해서 벡터 차원을 출력해.
   - 900자 안팎의 한글 문단 16개를 한 번에 임베딩하고, 걸린 시간으로 초당 조각 수를 재서 `config.json`의 `embed_chunks_per_sec`에 저장해.
   - 임베딩이 끝나면 `ollama ps`로 모델이 차지한 메모리를 보여 줘.
   - sqlite-vec를 불러와 `vec_version()`을 출력해. 보안 정책으로 확장 파일을 불러오지 못하면(접근 거부, 모듈을 찾을 수 없음 등) 그 사실을 알려 주고 멈춰.

## 망에서 막혔을 때

- 설치나 다운로드가 막히면, 막힌 주소와 대신 쓸 방법(사내 pip 미러, 다른 PC에서 받은 파일 반입)을 알려 주고 멈춰. 필요한 주소는 `ollama.com`, `github.com`, `release-assets.githubusercontent.com`(Ollama 설치 파일), `registry.ollama.ai`(모델), `pypi.org`, `files.pythonhosted.org`(sqlite-vec)야.
- 인증서 오류(SSL)가 나도 인증서 검증을 끄지 말고, 회사 인증서 설정이 필요하다고 알려 줘.
- 모델을 받을 때 프록시가 필요하면, Ollama에 `HTTPS_PROXY`만 설정하는 방법을 알려 줘. `HTTP_PROXY`는 설정하지 마.

## 마무리

끝나면 확인한 버전, 설치한 것, 잰 속도와 메모리, 남은 문제를 짧게 정리해 줘.
