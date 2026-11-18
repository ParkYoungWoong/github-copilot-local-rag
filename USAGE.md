# rag 명령 사용법(개발자용)

평소에는 Copilot에게 `/local-rag`로 요청하면 되고, 이 문서는 명령을 직접 쓰거나 다른 도구와 연결할 때 봅니다.
다른 프로젝트와 연결하는 방법은 [skill/local-rag/integration.md](skill/local-rag/integration.md)에 있습니다.

## rag

```text
rag scan <폴더> [--ext .md,.txt] [--exclude 패턴]
rag index <폴더> [--name 이름] [--desc 설명] [--ext ...] [--exclude ...] [--auto-refresh on|off]
rag index --name 이름 [--file 파일,...] [--only 패턴] [--rebuild] [--prune] [--dry-run]
          [--desc 설명] [--ext ...] [--exclude ...] [--auto-refresh on|off]
rag search "질문" (--name 이름 | --all) [-k 5] [--refresh | --no-refresh] [--json]
rag list [--json]
rag move <이름> <새 폴더> [--yes] [--force]
rag remove <이름> [--yes]
rag check
```

| 명령 | 하는 일 |
| --- | --- |
| `scan` | 저장하지 않고 대상 파일 수, 용량, 예상 조각 수와 시간, 건너뛸 파일, 제안 이름을 보여 줌 |
| `index <폴더>` | 컬렉션을 만듦. 같은 폴더의 컬렉션이 있으면 그것을 갱신. 이름을 안 주면 폴더 이름을 쓰고, 다른 폴더가 그 이름을 쓰고 있으면 상위 폴더 이름을 앞에 붙임 |
| `index --name` | 바뀐 파일만 다시 임베딩. `--file`은 지정한 파일만, `--only`는 패턴에 맞는 파일만, `--rebuild`는 전부 |
| `search` | 가까운 조각을 순위, 유사도, 파일, 제목, 수정일, 본문과 함께 출력. 자동 갱신이 켜져 있으면 바뀐 파일을 먼저 반영(예상 20초 이내일 때) |
| `move` | 원본 폴더를 옮겼을 때 새 경로를 알려 줌. 내용이 같은 파일은 다시 임베딩하지 않음. `--yes` 없이는 미리보기만 |
| `remove` | 색인 DB만 지움. `--yes` 없이는 지울 것만 보여 줌 |
| `check` | 이 PC의 설치 상태 점검(`setup/kit.py check`와 같음) |

동작 규칙:

- 파일 경로는 원본 폴더 기준 상대 경로를 `/`로 구분하고, 한글은 NFC로 맞춰 저장합니다. macOS나 외장 드라이브가 NFD로 돌려줘도 같은 파일로 봅니다.
- 원본 폴더가 없으면 아무것도 지우지 않습니다. 색인된 파일의 절반 넘게 사라져 보이면 `--prune`을 붙였을 때만 지웁니다.
- 내용이 같고 수정 시각만 바뀐 파일(복사한 파일 등)은 다시 임베딩하지 않고 수정 시각만 새로 기록합니다.
- `._*`, `.DS_Store`, `Thumbs.db`, `~$*` 같은 운영체제와 Office의 임시 파일은 조용히 건너뜁니다.
- Windows에서는 긴 경로(260자 초과)도 `\\?\` 접두사로 엽니다.

`--json` 출력 형식은 integration.md에 있습니다.

## setup/kit.py

```text
python setup/kit.py check
python setup/kit.py install [--yes] [--here] [--no-vscode]
python setup/kit.py prepare [--os windows,mac,linux]
python setup/kit.py copy-to <폴더> [--with-indexes]
python setup/kit.py uninstall [--yes]
```

| 명령 | 하는 일 |
| --- | --- |
| `install` | `--yes` 없이는 계획만 보여 줌. 가상 환경, sqlite-vec, Ollama, 모델, config.json(속도 측정), PATH와 `RAG_HOME`, 스킬, VS Code 자동 승인 규칙, 자체 시험 순서. `offline`에 파일이 있으면 인터넷에 접속하지 않음 |
| `prepare` | `offline`에 Ollama 설치 파일, Windows용 Python 설치 파일, 이 PC의 Ollama에서 꺼낸 모델 파일을 모음 |
| `copy-to` | `.venv`, `config.json`, 색인(`--with-indexes`가 없으면), 임시 파일을 빼고 복사 |
| `uninstall` | PATH, `RAG_HOME`, 스킬을 지움. Ollama, 모델, 색인은 남김 |

PC 설정을 바꾸는 곳:

| 운영체제 | PATH와 RAG_HOME | 스킬 | VS Code 설정 |
| --- | --- | --- | --- |
| Windows | 레지스트리 `HKCU\Environment`의 `Path`(원래 값 종류 유지), `RAG_HOME` | `%USERPROFILE%\.copilot\skills\local-rag` | `%APPDATA%\Code\User\settings.json` |
| macOS | `~/.zshrc`(bash면 `~/.bash_profile`)의 `# >>> local-rag >>>` 묶음 | `~/.copilot/skills/local-rag` | `~/Library/Application Support/Code/User/settings.json` |

바꾸기 전 파일은 이 폴더의 `backup/`에 남깁니다.

## 환경 변수

| 이름 | 쓰임 |
| --- | --- |
| `RAG_HOME` | 설치 때 등록. 스크립트에서 이 폴더를 찾을 때 씀 |
| `RAG_INDEX_DIR` | 색인 위치를 바꿈. 자체 시험에서만 씀 |
| `OLLAMA_MODELS` | Ollama 모델 폴더를 바꿨다면 설치 도우미도 이 값을 따름 |
