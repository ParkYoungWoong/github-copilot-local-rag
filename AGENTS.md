# 로컬 RAG 키트 폴더 안내(AI용)

이 폴더(키트 폴더)는 이 PC에 한 번 설치해 두고 여러 프로젝트에서 같이 쓰는 로컬 RAG 기본 환경입니다. GitHub에서 ZIP으로 받으면 폴더 이름이 `github-copilot-local-rag-main`이고, 반입용으로 복사하면 `local-rag`입니다.
GitHub Copilot, Claude Code, Codex 등 어느 AI 도구에서 열어도 이 문서의 절차는 같습니다. 설치하면 `rag` 명령과 `local-rag` 스킬이 여러 AI 도구에 함께 등록됩니다.
사용자는 대부분 개발자가 아닙니다. 필요한 명령은 직접 실행하고, 사용자에게 터미널 명령을 입력하거나 터미널에서 폴더를 옮기라고 하지 마세요.
이 폴더의 파일(`rag.py`, `setup/kit.py`, `skill/` 등)은 사용자가 고쳐 달라고 할 때만 고치세요.

## 받을 수 있는 요청

| 요청 예 | 할 일 |
| --- | --- |
| 설치해 줘 | [설치](#설치) |
| 반입 준비해 줘, 사내망으로 가져갈 준비해 줘, E 드라이브에 반입용으로 담아 줘 | [반입 준비](#반입-준비) |
| 점검해 줘 | [점검](#점검) |
| 어떤 모델을 쓸 수 있어?, 중국 모델 말고 다른 걸로 설치해 줘 | [임베딩 모델](#임베딩-모델) |
| 최신으로 업데이트해 줘, 새 버전으로 바꿔 줘 | [업데이트](#업데이트) |
| 이 폴더를 옮겼어, 다른 PC에서 가져왔어, 새 버전을 받았어 | [설치](#설치)를 다시 진행(새 위치에 맞춰 PATH, 스킬, 가상 환경을 다시 맞추고, 예전 폴더의 색인을 가져옴) |
| 설치를 지워 줘 | [설치 해제](#설치-해제) |
| 이걸 활용해서 ~ 예제를 만들어 줘, ~ 프로젝트에 적용해 줘 | `skill/local-rag/integration.md`의 절차. 예제는 이 폴더 밖에 만들고, 설치가 안 되어 있으면 설치부터 |
| 직접 만들어 보기 폴더를 만들어 줘 | 홈 폴더에 `local-rag-practice` 폴더를 만들고(이미 있으면 다른 이름을 물어봄) `1-setup.md`부터 `4-check-quality.md`까지 네 파일만 복사한 뒤, 그 폴더를 AI 도구에서 열고 `1-setup.md`를 첨부해 진행하라고 안내 |
| `1-setup.md` 같은 단계 파일을 첨부하고 진행해 달라는 요청 | 그 파일의 내용을 따름(강의용 '직접 만들어 보기'). 이 폴더에서 요청했다면 완성된 도구를 덮어쓰게 되니, 먼저 '직접 만들어 보기 폴더'를 만들자고 제안 |

## 오래 걸리는 명령

`setup/kit.py`의 `install --yes`, `pack`, `prepare`, `copy-to`, `add-model`과 `rag index`는 PC에 따라 몇 분에서 한 시간 가까이 걸립니다.

1. 실행할 때 기다리는 시간을 넉넉히(60분 이상) 잡고, 출력 마지막의 `[작업 끝]` 줄이 나올 때까지 기다립니다. 그 줄에 성공인지 실패인지가 나옵니다.
2. 도구가 그 줄이 나오기 전에 돌아오면(대기 시간 초과, 백그라운드로 옮김 등) 명령은 계속 실행 중입니다. 남은 출력을 이어서 확인하거나 같은 명령을 그대로 다시 실행합니다. 다시 실행하면 새로 시작하지 않고 진행 중인 작업에 이어 붙어 진행 상황과 결과를 보여 주고, 멈춘 작업이면 이어서 진행합니다. 설치는 10분 안에 성공으로 끝났으면 다시 하지 않고 그 결과를 보여 줍니다.
3. 오래 걸린다는 이유로 사용자에게 터미널에서 직접 실행하라고 하지 않습니다.

## 오류가 나면

`오류:` 줄, `[실패]` 줄, "다음에 할 일"을 읽고, 명령으로 할 수 있는 일(다른 Python으로 다시 실행, 홈 폴더로 복사, 같은 명령 다시 실행, `check`로 점검 등)은 직접 한 뒤 원래 명령을 다시 실행합니다.
사용자에게는 무엇을 했는지와 결과만 알리고, 사람만 할 수 있는 일(관리자 권한, 회사 보안 정책, 인증서, 디스크 공간 확보, PC 다시 시작)만 쉬운 말로 부탁합니다.
같은 오류가 두 번 나면 더 시도하지 말고 `오류:` 줄을 그대로 보여 주며 알립니다.

## 확인을 받는 방법

확인이 필요할 때는 질문 도구(선택지 창 등)에 기대지 말고, 답변에 물어볼 내용을 쓰고 그 차례를 마치세요. 사용자가 답하면 이어서 진행합니다.
질문 도구가 "사용자가 답할 수 없다"고 돌려주면 확인을 받지 못한 것으로 보고, PC 설정을 바꾸는 명령은 실행하지 마세요.

## Python 찾기

`setup/kit.py`는 표준 라이브러리만 쓰므로 Python 3.10 이상이면 됩니다. 아래 순서로 찾고, 찾은 Python의 전체 경로를 이 문서에서 `<python>`이라고 부릅니다.

- Windows(PowerShell)
  1. `Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:LOCALAPPDATA\Python\pythoncore-3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue`. 이름이 `-32`(32비트)나 `-arm64`(ARM용)로 끝나는 폴더는 건너뜁니다. sqlite-vec는 Windows x64 Python용만 있습니다.
  2. `python -c "import sys; print(sys.executable)"`. 아무것도 출력되지 않거나, 경로에 `\WindowsApps\`가 들어 있거나, Microsoft Store가 열리면 Store 바로 가기나 Store용 Python이니 건너뜁니다.
  3. `py` 명령은 쓰지 않습니다. 새 Python 설치 관리자는 Python이 없으면 인터넷에서 자동으로 받으려고 해서 사내망에서 멈출 수 있습니다.
  4. 모두 없으면 `offline\python\windows\`의 설치 파일을 확인합니다. 있으면 Python을 설치한다고 알리고 확인을 받은 뒤 아래처럼 설치합니다(관리자 권한 없이 사용자 계정에만 설치). 끝나면 1번으로 다시 찾습니다.
     ```powershell
     Start-Process -Wait -FilePath "<설치 파일 전체 경로>" -ArgumentList "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0"
     ```
     설치 파일도 없으면 python.org에서 Windows x64 Python을 설치하라고 안내하고 멈춥니다.
  5. PowerShell에서 따옴표로 감싼 경로로 실행할 때는 앞에 `&`를 붙입니다. 예: `& "<python>" setup\kit.py install`. `kit.py`가 출력하는 명령은 이미 이 형식입니다.
- macOS
  1. `python3.14`, `python3.13`, `python3.12`, `python3.11`, `python3.10`
  2. `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`
  3. `python3`. macOS 기본 Python(`/usr/bin/python3`), python.org의 macOS용 Python, 일부 설치 도구로 만든 Python(GitHub Actions의 setup-python 등)은 SQLite 확장을 불러오지 못해서 `kit.py`가 알려 줍니다. 그러면 위 목록의 다른 Python으로 다시 실행하고, 모두 안 되면 Homebrew Python(`brew install python`)을 설치하라고 안내하고 멈춥니다.

## 설치

1. `<python> setup/kit.py install`을 실행해서 설치 계획을 받습니다. 이 명령은 아무것도 바꾸지 않습니다.
   - "설치를 멈췄습니다"가 나오면(외장 드라이브, 동기화 폴더 등) 이유를 알리고, 확인을 받은 뒤 출력에 나온 `copy-to` 명령으로 홈 폴더에 복사합니다. 그다음 복사한 폴더의 `setup/kit.py`로 1번부터 이어서 진행합니다. 복사한 폴더를 AI 도구에서 다시 열 필요는 없습니다.
2. 계획을 짧게 보여 주고, `[PC 설정 변경]`이 붙은 항목을 짚어서 진행해도 되는지 물어본 뒤 차례를 마칩니다. 이때 함께 알립니다.
   - 기본 임베딩 모델은 Qwen3(Alibaba, 중국)이고, 회사에서 중국 모델을 쓸 수 없으면 Google, Snowflake 모델로 바꿀 수 있다는 것(후보는 [임베딩 모델](#임베딩-모델))
   - 설치에 몇 분에서 수십 분이 걸리고, 진행 상황은 브라우저에 열리는 '로컬 RAG 설치' 화면에서 볼 수 있다는 것
3. 진행하라는 답을 받으면 `<python> setup/kit.py install --yes`를 실행합니다. 다른 모델을 골랐으면 `--model <모델>`을, 자동 승인 규칙을 원하지 않으면 `--no-auto-approve`를 붙입니다. Ollama 설치(Windows는 약 1.8GB)와 모델 받기 때문에 오래 걸리니 [오래 걸리는 명령](#오래-걸리는-명령)대로 끝까지 기다립니다.
4. 실패하면 [오류가 나면](#오류가-나면)대로 처리합니다. 자체 시험의 `[실패]` 줄이 남으면 그 줄을 그대로 전합니다. 출력에 VS Code 규칙을 "직접 넣어야 함"이 나오면, 그 규칙을 사용자 설정(`settings.json`)의 `chat.tools.terminal.autoApprove`에 넣어도 되는지 묻고, 확인을 받으면 기존 설정은 그대로 둔 채 넣습니다.
5. 끝나면 출력의 'rag 실행 파일' 경로로 `list`를 실행해(예: Windows PowerShell은 `& "<키트 폴더>\bin\rag.cmd" list`) 동작을 확인하고, 결과를 짧게 알립니다. 그다음 아무 프로젝트에서 새 대화를 열고 "/local-rag 목록 보여 줘"로 확인하라고 안내합니다. 스킬이 보이지 않으면 AI 도구(VS Code 등)를 완전히 종료했다가 다시 열라고 안내합니다.

망에서 막혔을 때:

- 인증서 오류(SSL)가 나도 인증서 검증을 끄지 말고, 회사 인증서 설정이 필요하다고 알립니다.
- 인터넷에서 받아야 하는데 막혔다면, 인터넷이 되는 PC에서 "반입 준비해 줘"로 준비한 폴더를 가져오라고 안내합니다. 필요한 주소는 `ollama.com`, `github.com`, `release-assets.githubusercontent.com`(Ollama 설치 파일), `registry.ollama.ai`(모델), `pypi.org`, `files.pythonhosted.org`(sqlite-vec), `www.python.org`(Windows용 Python)입니다.
- Ollama가 프록시를 거쳐 모델을 받아야 하면 Ollama에 `HTTPS_PROXY`만 설정하는 방법을 알려 줍니다. `HTTP_PROXY`는 설정하지 않습니다.
- 터미널에서 `ollama serve`를 직접 실행하지 않습니다. Ollama가 꺼져 있으면 `kit.py`와 `rag`가 앱을 켜고, 앱이 응답하지 않으면 서버를 따로 띄웁니다. 그래도 안 되면 오류에 붙은 Ollama 기록을 보고 [오류가 나면](#오류가-나면)대로 처리합니다.

## 업데이트

이미 설치한 PC에서 키트를 최신으로 바꾸는 일입니다. 색인(컬렉션)은 그대로 이어서 씁니다.

1. 키트 폴더에 `.git` 폴더가 있으면(git clone으로 받은 경우) `git -C "<키트 폴더>" pull --ff-only`를 실행합니다.
   - 성공하면 [설치](#설치)를 1번부터 다시 진행합니다. 같은 폴더라 가상 환경과 색인은 그대로 쓰고, 스킬과 실행 파일만 새것으로 바뀝니다.
   - "local changes" 같은 오류로 실패하면 `git status --short`로 바뀐 파일을 보여 주고, 그 변경을 잠시 치워 둬도 되는지 물어봅니다. 확인을 받으면 `git -C "<키트 폴더>" stash` 뒤에 다시 pull합니다. 치워 둔 변경은 지워지지 않고 남아 있으며, 필요하면 `git stash pop`으로 되돌릴 수 있다고 알립니다.
2. `.git` 폴더가 없으면(ZIP으로 받은 경우) 새 ZIP을 받아 홈 폴더에 지금 폴더와 다른 이름으로 풉니다. 주소는 `https://github.com/ParkYoungWoong/github-copilot-local-rag/archive/refs/heads/main.zip`이고, Windows는 `curl.exe -L -o`와 `Expand-Archive`, macOS는 `curl -L -o`와 `unzip`을 씁니다.
   - 압축을 푼 폴더의 `setup/kit.py`로 [설치](#설치)를 1번부터 진행합니다. 예전 키트 폴더의 색인은 설치할 때 새 폴더로 가져옵니다.
   - 끝나면 예전 키트 폴더는 지워도 된다고 알립니다. 지우는 것은 사용자가 원할 때만 합니다.
3. 인터넷이 막힌 PC라면 인터넷이 되는 PC에서 새로 반입 준비한 폴더를 가져와 [설치](#설치)를 진행합니다.

## 반입 준비

인터넷이 되는 PC에서, 사내망 PC에 가져갈 폴더를 외장 드라이브에 한 번에 만드는 일입니다. 이 PC에 설치하지 않아도 됩니다.

1. Python만 있으면 됩니다. [Python 찾기](#python-찾기) 순서로 찾습니다.
2. 한 번에 물어봅니다: 외장 드라이브 위치(예: `E:\`, macOS는 `/Volumes/<이름>`), 사내 PC의 운영체제(기본 Windows), 임베딩 모델(기본 Qwen3, 중국 모델이 안 되면 [임베딩 모델](#임베딩-모델)의 후보), 이 PC에서 만든 색인도 가져갈지(기본은 가져가지 않음).
3. 답을 받으면 `<python> setup/kit.py pack "<드라이브>\local-rag" --os windows`를 실행합니다(macOS는 `/Volumes/<이름>/local-rag`). 모델을 골랐으면 `--model <모델>`(여러 개면 쉼표로, 첫 번째가 기본), 사내 PC가 둘 다면 `--os windows,mac`, 색인도 가져가면 `--with-indexes`를 붙입니다. 색인에는 문서 내용 조각이 들어 있으니 반출 규정을 확인하라고 알립니다.
   - 재료를 받고(Windows 기준 약 2.5GB), 외장 드라이브로 복사하고, 복사한 파일을 확인한 뒤, 그 폴더에 `반입 안내.txt`를 만듭니다. 진행 상황은 브라우저의 '로컬 RAG 반입 준비' 화면에서 볼 수 있다고 알립니다.
4. 끝나면 "외장 드라이브의 `local-rag` 폴더 하나만 가져가면 되고, 사내 PC에서는 그 폴더를 AI 도구에서 열고 '설치해 줘'라고 요청하면 된다"고 안내합니다.

외장 드라이브 없이 재료만 이 폴더의 `offline`에 모으려면 `<python> setup/kit.py prepare --os windows`를, 이미 모은 폴더를 복사만 하려면 `<python> setup/kit.py copy-to "<폴더>"`를 씁니다.

## 임베딩 모델

`<python> setup/kit.py models`로 후보를 봅니다(설치한 뒤라면 `rag models`도 같습니다). 후보와 기준은 `models.json`에 있습니다.

| 모델 | 만든 곳 | 특징 |
| --- | --- | --- |
| `qwen3-embedding:0.6b` | Alibaba(중국) | 기본. 긴 문서도 잘리지 않음(약 640MB) |
| `embeddinggemma:300m` | Google(미국) | 중국 모델을 쓸 수 없을 때 먼저 고를 대안. 한국어 검색 품질이 기본과 비슷하고 색인이 빠름(Windows 약 9배, Mac 약 2.5배, 약 620MB, Gemma 이용 약관) |
| `snowflake-arctic-embed2:568m` | Snowflake(미국) | 검색 품질이 기본과 비슷, 파일이 큼(약 1.2GB). 바탕 모델은 중국 BAAI의 bge-m3 |

검색 품질은 키트의 한국어 문서 18개, 질문 43개로 잰 결과입니다. 회사 규정이 모델을 만든 곳만 보는지, 바탕 모델까지 보는지에 따라 고르세요.

- 설치할 때 고르면 `install --yes --model <모델>`입니다.
- 설치한 뒤에 모델을 더 받거나 기본을 바꾸려면 `rag models --add <모델>`(기본으로 바꾸려면 `--default`)입니다. 기존 컬렉션은 만들 때의 모델을 그대로 씁니다.

## 점검

`<python> setup/kit.py check`를 실행합니다(설치가 끝난 뒤라면 `rag check`도 같습니다). `[실패]`와 `[확인 필요]` 항목의 "다음에 할 일" 중 명령으로 할 수 있는 것은 직접 하고 다시 점검한 뒤, 결과와 남은 일만 짧게 정리합니다.

## 설치 해제

`<python> setup/kit.py uninstall`로 지울 것을 보여 주고, 확인을 받으면 `--yes`를 붙여 실행합니다. Ollama, 모델, 색인은 지우지 않습니다.
