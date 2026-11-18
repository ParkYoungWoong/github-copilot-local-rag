# 로컬 RAG 키트 폴더 안내(AI용)

이 폴더(키트 폴더)는 이 PC에 한 번 설치해 두고 여러 프로젝트에서 같이 쓰는 로컬 RAG 기본 환경입니다. GitHub에서 ZIP으로 받으면 폴더 이름이 `github-copilot-local-rag-main`이고, 반입용으로 복사하면 `local-rag`입니다.
사용자는 대부분 개발자가 아닙니다. 필요한 명령은 직접 실행하고, 사용자에게 터미널 명령을 입력하거나 터미널에서 폴더를 옮기라고 하지 마세요.
이 폴더의 파일(`rag.py`, `setup/kit.py`, `skill/` 등)은 사용자가 고쳐 달라고 할 때만 고치세요.

## 받을 수 있는 요청

| 요청 예 | 할 일 |
| --- | --- |
| 설치해 줘 | [설치](#설치) |
| 반입 준비해 줘, 사내망으로 가져갈 준비해 줘 | [반입 준비](#반입-준비) |
| E 드라이브에 반입용으로 복사해 줘 | [반입 준비](#반입-준비)의 3번 |
| 점검해 줘 | [점검](#점검) |
| 이 폴더를 옮겼어, 다른 PC에서 가져왔어 | [설치](#설치)를 다시 진행(새 위치에 맞춰 PATH, 스킬, 가상 환경을 다시 맞춤) |
| 설치를 지워 줘 | [설치 해제](#설치-해제) |
| 이걸 활용해서 ~ 예제를 만들어 줘, ~ 프로젝트에 적용해 줘 | `skill/local-rag/integration.md`의 절차. 예제는 이 폴더 밖에 만들고, 설치가 안 되어 있으면 설치부터 |
| 직접 만들어 보기 폴더를 만들어 줘 | 홈 폴더에 `local-rag-practice` 폴더를 만들고(이미 있으면 다른 이름을 물어봄) `1-setup.md`부터 `4-check-quality.md`까지 네 파일만 복사한 뒤, 그 폴더를 VS Code로 열고 `1-setup.md`를 첨부해 진행하라고 안내 |
| `1-setup.md` 같은 단계 파일을 첨부하고 진행해 달라는 요청 | 그 파일의 내용을 따름(강의용 '직접 만들어 보기'). 이 폴더에서 요청했다면 완성된 도구를 덮어쓰게 되니, 먼저 '직접 만들어 보기 폴더'를 만들자고 제안 |

## Python 찾기

`setup/kit.py`는 표준 라이브러리만 쓰므로 Python 3.10 이상이면 됩니다. 아래 순서로 찾고, 찾은 Python의 전체 경로를 이 문서에서 `<python>`이라고 부릅니다.

- Windows(PowerShell)
  1. `Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:LOCALAPPDATA\Python\pythoncore-3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue`. 이름이 `-32`로 끝나는 폴더(32비트)는 건너뜁니다.
  2. `python -c "import sys; print(sys.executable)"`. 아무것도 출력되지 않거나, 경로에 `\WindowsApps\`가 들어 있거나, Microsoft Store가 열리면 Store 바로 가기나 Store용 Python이니 건너뜁니다.
  3. `py` 명령은 쓰지 않습니다. 새 Python 설치 관리자는 Python이 없으면 인터넷에서 자동으로 받으려고 해서 사내망에서 멈출 수 있습니다.
  4. 모두 없으면 `offline\python\windows\`의 설치 파일을 확인합니다. 있으면 사용자에게 Python을 설치한다고 알리고 확인을 받은 뒤 아래처럼 설치합니다(관리자 권한 없이 사용자 계정에만 설치). 끝나면 1번으로 다시 찾습니다.
     ```powershell
     Start-Process -Wait -FilePath "<설치 파일 전체 경로>" -ArgumentList "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0"
     ```
     설치 파일도 없으면 python.org에서 Python을 설치하라고 안내하고 멈춥니다.
  5. PowerShell에서 따옴표로 감싼 경로로 실행할 때는 앞에 `&`를 붙입니다. 예: `& "<python>" setup\kit.py install`. `kit.py`가 출력하는 명령은 이미 이 형식입니다.
- macOS
  1. `python3.14`, `python3.13`, `python3.12`, `python3.11`, `python3.10`
  2. `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`, `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`
  3. `python3`. macOS 기본 Python(`/usr/bin/python3`)은 확장을 불러오지 못해서 `kit.py`가 알려 줍니다. 그러면 Homebrew나 python.org의 Python을 설치하라고 안내하고 멈춥니다.

## 설치

1. `<python> setup/kit.py install`을 실행해서 설치 계획을 받습니다. 이 명령은 아무것도 바꾸지 않습니다.
   - "설치를 멈췄습니다"가 나오면(외장 드라이브, 동기화 폴더 등) 이유를 알리고, 확인을 받은 뒤 출력에 나온 `copy-to` 명령으로 홈 폴더에 복사합니다. 그다음 복사한 폴더의 `setup/kit.py`로 1번부터 이어서 진행합니다. 복사한 폴더를 VS Code로 다시 열 필요는 없습니다.
2. 계획을 사용자에게 보여 주고, `[PC 설정 변경]`이 붙은 항목을 짚어서 확인을 받습니다.
3. `<python> setup/kit.py install --yes`를 실행합니다. 사용자가 VS Code 자동 승인 규칙을 원하지 않으면 `--no-vscode`를 붙입니다. Ollama 설치와 모델 복사 때문에 몇 분 걸릴 수 있으니 끝날 때까지 기다립니다.
4. 실패하면 `오류:` 줄과 "다음에 할 일"을 그대로 전하고 멈춥니다. 출력에 VS Code 규칙을 "직접 넣어야 함"이 나오면, 그 규칙을 사용자 설정(`settings.json`)의 `chat.tools.terminal.autoApprove`에 넣어도 되는지 묻고, 확인을 받으면 기존 설정은 그대로 둔 채 넣습니다.
5. 끝나면 결과를 짧게 알리고, VS Code를 완전히 종료했다가 다시 연 뒤 아무 프로젝트에서 새 대화를 열고 "/local-rag 목록 보여 줘"로 확인하라고 안내합니다.

망에서 막혔을 때:

- 인증서 오류(SSL)가 나도 인증서 검증을 끄지 말고, 회사 인증서 설정이 필요하다고 알립니다.
- 인터넷에서 받아야 하는데 막혔다면, 인터넷이 되는 PC에서 "반입 준비해 줘"로 준비한 폴더를 가져오라고 안내합니다. 필요한 주소는 `ollama.com`, `github.com`, `release-assets.githubusercontent.com`(Ollama 설치 파일), `registry.ollama.ai`(모델), `pypi.org`, `files.pythonhosted.org`(sqlite-vec), `www.python.org`(Windows용 Python)입니다.
- Ollama가 프록시를 거쳐 모델을 받아야 하면 Ollama에 `HTTPS_PROXY`만 설정하는 방법을 알려 줍니다. `HTTP_PROXY`는 설정하지 않습니다.
- 터미널에서 `ollama serve`를 실행하지 않습니다. Ollama가 꺼져 있으면 Ollama 앱을 실행하라고 안내합니다.

## 반입 준비

인터넷이 되는 PC에서, 사내망 PC에 가져갈 설치 재료를 이 폴더의 `offline`에 모으는 일입니다.

이 PC에 설치하지 않아도 됩니다. 이 PC에 Ollama와 모델이 이미 있으면 그 모델 파일을 쓰고, 없으면 모델 저장소에서 직접 받습니다.

1. Python만 있으면 됩니다. [Python 찾기](#python-찾기) 순서로 찾습니다.
2. 사내 PC가 Windows인지 macOS인지 묻습니다(기본은 Windows). `<python> setup/kit.py prepare --os windows`를 실행합니다. 둘 다면 `--os windows,mac`입니다. Windows 기준 약 2.5GB를 받으므로 시간이 걸린다고 알립니다.
3. 끝나면 외장 드라이브 위치를 묻고 `<python> setup/kit.py copy-to "<드라이브>\local-rag"`로 복사합니다(macOS는 `/Volumes/<드라이브 이름>/local-rag`).
   - 이 PC에서 만든 색인도 가져갈지 묻습니다. 기본은 가져가지 않습니다. 가져가면 `--with-indexes`를 붙이고, 색인에 문서 내용 조각이 들어 있으니 반출 규정을 확인하라고 알립니다.
4. 사내 PC에서는 외장 드라이브의 `local-rag` 폴더를 VS Code로 열고 "설치해 줘"라고 요청하면 된다고 안내합니다. 홈 폴더로 복사하는 것부터 Copilot이 처리합니다.

## 점검

`<python> setup/kit.py check`를 실행합니다(설치가 끝난 뒤라면 `rag check`도 같습니다). `[실패]`와 `[확인 필요]` 항목을 "다음에 할 일"과 함께 짧게 정리합니다.

## 설치 해제

`<python> setup/kit.py uninstall`로 지울 것을 보여 주고, 확인을 받으면 `--yes`를 붙여 실행합니다. Ollama, 모델, 색인은 지우지 않습니다.
