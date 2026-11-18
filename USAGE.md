# rag 명령 사용법(개발자용)

평소에는 AI에게 `/local-rag`로 요청하면 되고, 이 문서는 명령을 직접 쓰거나 다른 도구와 연결할 때 봅니다.
다른 프로젝트와 연결하는 방법은 [skill/local-rag/integration.md](skill/local-rag/integration.md)에 있습니다.

## rag

```text
rag scan <폴더> [--ext .md,.txt] [--exclude 패턴] [--model 모델]
rag index <폴더> [--name 이름] [--desc 설명] [--ext ...] [--exclude ...] [--auto-refresh on|off] [--model 모델]
rag index --name 이름 [--file 파일,...] [--only 패턴] [--rebuild] [--prune] [--dry-run]
          [--desc 설명] [--ext ...] [--exclude ...] [--auto-refresh on|off] [--model 모델]
rag search "질문" (--name 이름 | --all) [-k 5] [--refresh | --no-refresh] [--json]
rag list [--json]
rag move <이름> <새 폴더> [--yes] [--force]
rag remove <이름> [--yes]
rag models [--add 모델 [--default]] [--json]
rag check
```

| 명령 | 하는 일 |
| --- | --- |
| `scan` | 저장하지 않고 대상 파일 수, 용량, 예상 조각 수와 시간, 건너뛸 파일, 제안 이름을 보여 줌 |
| `index <폴더>` | 컬렉션을 만듦. 같은 폴더의 컬렉션이 있으면 그것을 갱신. 이름을 안 주면 '프로젝트-폴더-해시'(예: `memo1-wiki-3f9a`). 프로젝트는 가장 가까운 상위 폴더 중 `.git`, `AGENTS.md`, `package.json` 같은 표시가 있는 곳이고, 해시는 폴더 경로의 SHA-1 앞 4자리(겹치면 더 길게) |
| `index --name` | 바뀐 파일만 다시 임베딩. `--file`은 지정한 파일만, `--only`는 패턴에 맞는 파일만, `--rebuild`는 전부. `--model`이 컬렉션의 모델과 다르면 임시 DB에 새로 만든 뒤 바꿔 끼움 |
| `search` | 가까운 조각을 순위, 유사도, 파일, 제목, 수정일, 본문과 함께 출력. 자동 갱신이 켜져 있으면 바뀐 파일을 먼저 반영(예상 20초 이내일 때) |
| `move` | 원본 폴더를 옮겼을 때 새 경로를 알려 줌. 내용이 같은 파일은 다시 임베딩하지 않음. `--yes` 없이는 미리보기만 |
| `remove` | 색인 DB만 지움. `--yes` 없이는 지울 것만 보여 줌 |
| `models` | `models.json`의 후보와 받았는지, 쓰는 컬렉션을 보여 줌. `--add`는 모델을 받고 속도를 잼(`--default`면 새 컬렉션의 기본으로) |
| `check` | 이 PC의 설치 상태 점검(`setup/kit.py check`와 같음) |

동작 규칙:

- 파일 경로는 원본 폴더 기준 상대 경로를 `/`로 구분하고, 한글은 NFC로 맞춰 저장합니다. macOS나 외장 드라이브가 NFD로 돌려줘도 같은 파일로 봅니다.
- 원본 폴더가 없으면 아무것도 지우지 않습니다. 색인된 파일의 절반 넘게 사라져 보이면 `--prune`을 붙였을 때만 지웁니다.
- 내용이 같고 수정 시각만 바뀐 파일(복사한 파일 등)은 다시 임베딩하지 않고 수정 시각만 새로 기록합니다.
- `._*`, `.DS_Store`, `Thumbs.db`, `~$*` 같은 운영체제와 Office의 임시 파일은 조용히 건너뜁니다.
- Windows에서는 긴 경로(260자 초과)도 `\\?\` 접두사로 엽니다.
- 컬렉션마다 만들 때 쓴 모델(`metadata.model`)로 문서와 질문을 임베딩합니다. 모델마다 질문과 문서 형식은 `models.json`의 `query`, `document`에 있고(`{question}`, `{instruction}`, `{title}`, `{text}`), 목록에 없는 모델은 형식 없이 씁니다.
- Windows에서 출력을 파이프로 받으면(AI 도구의 터미널 등) UTF-8로 씁니다. 콘솔에 바로 쓸 때는 Windows가 유니코드로 처리합니다.
- `index`(`--dry-run` 제외)는 컬렉션마다 한 번에 하나만 돕니다. 같은 명령을 다시 실행하면 진행 중인 작업에 이어 붙어 진행 상황과 결과를 보여 주고, 옵션이 다르면 앞 작업이 끝난 뒤 시작합니다. 앞 작업이 중간에 꺼졌으면 이어서 진행합니다. 잠금과 진행 기록은 `indexes/.jobs/`에 있고, 출력은 `[작업 시작]`으로 시작해 `[작업 끝] ... 성공` 또는 `실패(종료 코드 N)`로 끝납니다.
- 파이프로 읽을 때 진행률은 10%마다 또는 15초마다 한 줄씩 쓰고, 출력이 30초 넘게 없으면 '아직 진행 중' 줄을 씁니다(AI 도구가 멈춘 명령으로 보지 않게).
- 색인 중인 컬렉션을 검색하면 자동 갱신을 건너뛰고 지금까지 만든 색인으로 찾습니다.
- Ollama가 꺼져 있으면 앱을 켜고, 앱이 응답하지 않으면 서버를 따로 띄운 뒤 다시 시도합니다(`ollama_url`이 이 PC일 때만).

`--json` 출력 형식은 integration.md에 있습니다.

## setup/kit.py

```text
python setup/kit.py check
python setup/kit.py install [--yes] [--here] [--model 모델] [--no-auto-approve] [--no-browser]
python setup/kit.py models
python setup/kit.py add-model <모델> [--default]
python setup/kit.py pack <외장 드라이브 폴더> [--os windows,mac] [--model 모델,...] [--with-indexes] [--no-browser]
python setup/kit.py prepare [--os windows,mac,linux] [--model 모델,...] [--no-browser]
python setup/kit.py copy-to <폴더> [--with-indexes]
python setup/kit.py uninstall [--yes]
```

| 명령 | 하는 일 |
| --- | --- |
| `install` | `--yes` 없이는 계획만 보여 줌. 가상 환경, sqlite-vec, Ollama, 모델(기본, 컬렉션이 쓰는 것, 반입해 온 것), config.json(속도 측정), PATH와 `RAG_HOME`과 바로 쓰는 실행 파일, 세 곳의 스킬, VS Code와 Claude Code 자동 승인 규칙, 예전 키트 폴더의 색인 가져오기, 자체 시험 순서. `offline`에 파일이 있으면 인터넷에 접속하지 않음. 진행 상황 화면(`progress.html`)을 브라우저로 엶 |
| `pack` | 반입 준비를 한 번에: `prepare` 뒤 외장 드라이브로 복사(다른 운영체제의 설치 파일은 뺌), 크기와 모델 파일 확인, `반입 안내.txt` 작성 |
| `prepare` | `offline`에 Ollama 설치 파일, Windows용 Python 설치 파일, 모델 파일을 모음. 모델은 이 PC의 Ollama에 있으면 복사하고, 없으면 모델 저장소에서 직접 받음 |
| `add-model` | 모델을 받고(반입 파일 우선) 속도를 잼. `--default`면 config.json의 기본 모델을 바꿈 |
| `copy-to` | `.venv`, `config.json`, 색인(`--with-indexes`가 없으면), 임시 파일을 빼고 복사 |
| `uninstall` | PATH, `RAG_HOME`, 바로 쓰는 실행 파일, 세 곳의 스킬을 지움. Ollama, 모델, 색인, 자동 승인 규칙은 남김 |

`install --yes`, `pack`, `prepare`, `copy-to`, `add-model`도 `rag index`처럼 한 번에 하나만 돌고, 다시 실행하면 진행 중인 작업에 이어 붙습니다(기록은 `.jobs/`). `install --yes`는 같은 설치가 10분 안에 성공으로 끝났고, 키트 파일이 그대로이며, `check`에 실패가 없으면 다시 하지 않고 그 결과를 보여 줍니다. `uninstall --yes`는 이 기록도 지웁니다.

PC 설정을 바꾸는 곳:

| 운영체제 | PATH와 RAG_HOME | 바로 쓰는 실행 파일 | 스킬 | 자동 승인 규칙 |
| --- | --- | --- | --- | --- |
| Windows | 레지스트리 `HKCU\Environment`의 `Path`(원래 값 종류 유지), `RAG_HOME` | `%LOCALAPPDATA%\Microsoft\WindowsApps\rag.cmd`(Windows 기본 PATH에 있는 폴더) | `%USERPROFILE%\.agents`, `.claude`, `.copilot`의 `skills\local-rag` | `%APPDATA%\Code\User\settings.json`, `%USERPROFILE%\.claude\settings.json` |
| macOS | `~/.zshrc`(bash면 `~/.bash_profile`)의 `# >>> local-rag >>>` 묶음 | `~/.local/bin/rag`(이미 PATH에 있을 때만) | `~/.agents`, `~/.claude`, `~/.copilot`의 `skills/local-rag` | `~/Library/Application Support/Code/User/settings.json`, `~/.claude/settings.json` |

바로 쓰는 실행 파일은 설치 전에 열어 둔 AI 도구가 옛 PATH를 그대로 쓰는 문제 때문에 둡니다. 설치한 스킬의 SKILL.md 끝에는 이 PC의 `rag` 전체 경로를 적어, 그래도 못 찾으면 AI가 전체 경로로 실행하게 합니다.

바꾸기 전 파일은 이 폴더의 `backup/`에 남깁니다.

## 환경 변수

| 이름 | 쓰임 |
| --- | --- |
| `RAG_HOME` | 설치 때 등록. 스크립트에서 이 폴더를 찾을 때 씀 |
| `RAG_INDEX_DIR` | 색인 위치를 바꿈. 자체 시험에서만 씀 |
| `RAG_NO_JOB` | 값이 있으면 색인, 설치를 잠금 없이 바로 실행(문제를 찾을 때만) |
| `OLLAMA_MODELS` | Ollama 모델 폴더를 바꿨다면 설치 도우미도 이 값을 따름 |
