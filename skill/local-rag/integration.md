# 로컬 RAG를 프로젝트와 예제에 적용하기

`local-rag` 스킬이 "이 프로젝트에 적용해 줘", "local-rag를 활용하는 예제를 만들어 줘" 같은 요청을 받았을 때 따르는 절차입니다.
로컬 RAG 자체(`rag` 명령, 색인, 모델)는 이 PC에 한 번만 설치되어 있고, 프로젝트에는 사용법을 적은 지침이나 스킬만 넣습니다.

## 먼저 확인

- `rag list`가 실행되는지 확인하세요. 실행되지 않으면 SKILL.md의 공통 규칙대로 안내하고 멈추세요.
- 다음은 프로젝트에 넣지 마세요: `rag.py`나 색인(`.db`) 복사본, Ollama나 sqlite-vec를 직접 부르는 코드, 이 PC의 절대 경로가 박힌 설정.

## 프로젝트에 적용

1. 문서 폴더를 찾으세요. 작업 폴더에서 `docs`, `문서`, `wiki`, `규정`, `매뉴얼`처럼 `.md`, `.txt` 파일이 모인 폴더를 찾고, 소스 코드, 빌드 결과, 의존성 폴더는 빼세요.
   - 후보가 여럿이면 폴더와 파일 수를 표로 보여 주고 고르게 하세요.
   - 후보가 없으면 어떤 문서를 RAG로 만들지 물어보세요. `.docx`, `.pdf`는 마크다운으로 바꿔야 한다고 알리세요.
2. 고른 폴더마다 SKILL.md의 '폴더를 RAG로 만들기' 절차로 컬렉션을 만드세요. 이미 같은 폴더의 컬렉션이 있으면 갱신만 하세요.
   - 프로젝트의 지침 파일이나 스킬에 컬렉션 이름이 이미 적혀 있으면(팀원이 먼저 적용한 경우), 제안 이름 대신 그 이름을 `--name`으로 쓰세요. 그래야 모든 PC에서 같은 지침이 그대로 동작합니다.
3. 프로젝트 지침에 사용법을 넣으세요. 작업 폴더 맨 위에 `AGENTS.md`가 있으면 거기에, 없으면 `.github/copilot-instructions.md`에 넣으세요(없으면 만드세요). 넣기 전에 바꿀 내용을 보여 주고 확인을 받으세요. 같은 표시(`local-rag:start`)가 이미 있으면 그 사이만 바꾸고, 없으면 파일 맨 끝에 빈 줄 하나를 두고 붙이세요. 기존 목록이나 절 중간에 끼워 넣지 마세요.

   ```markdown
   <!-- local-rag:start -->
   ## 문서 검색(local-rag)

   - `docs` 폴더의 내용을 묻는 질문은 파일을 직접 열기 전에 `local-rag` 스킬로 `docs` 컬렉션을 먼저 검색해서 답해(`rag search "<질문>" --name docs`).
   - 답 끝에 출처(컬렉션, 파일, 제목, 수정일)를 붙여.
   - 이 PC에서 `rag` 명령을 쓸 수 없으면 폴더의 파일을 직접 찾아 답하고, 로컬 RAG가 설치되지 않았다고 알려.
   <!-- local-rag:end -->
   ```

   폴더 이름(`docs`)과 컬렉션 이름은 실제 값으로 바꾸세요. 컬렉션이 여럿이면 폴더마다 한 줄씩 쓰세요.
4. 문서에 있는 질문 하나로 `rag search`를 실행해서 검색되는 것을 보여 주세요.
5. 끝나면 다음을 짧게 알리세요.
   - 지침은 새 대화부터 적용된다는 것
   - 지침 파일과 문서는 저장소에 올려도 되지만 색인은 PC마다 만든다는 것. 팀원은 자기 PC에 로컬 RAG를 설치하고 이 프로젝트에서 "/local-rag 이 프로젝트에 적용해 줘"라고 하면 같은 이름의 컬렉션이 만들어집니다.

## 활용 예제 만들기

1. 예제 폴더는 키트 폴더(로컬 RAG를 설치한 폴더) 밖에 만드세요. 위치를 정하지 않았으면 지금 연 작업 폴더에 만드세요.
2. 문서를 준비하세요. 사용자가 문서를 주면 그것을 쓰고, 주제만 주면 그 주제로 `docs` 폴더에 짧은 마크다운 문서 3~5개를 만드세요. 문서마다 제목과 소제목을 달고, 숫자나 기준처럼 검색으로 확인할 수 있는 내용을 넣으세요.
3. 아래 패턴 중 요청에 맞는 것을 고르세요. 모르겠으면 A로 하세요.
4. `README.md`에 예제가 하는 일, 컬렉션 이름, 시험 질문 3개(문서에 있는 질문 2개, 없는 질문 1개)를 쓰세요.
5. '프로젝트에 적용'의 2~4단계로 컬렉션과 지침을 만들고, 시험 질문으로 확인한 결과를 보여 주세요.

## 패턴

### A. 지침만 넣기

가장 쉬운 방법입니다. 위 '프로젝트에 적용'의 지침 묶음만 넣으면, 문서 질문을 받을 때 Copilot이 `local-rag` 스킬로 찾아 답합니다.

### B. 프로젝트 스킬

팀 FAQ 답변, 규정 확인처럼 정해진 업무를 문서 근거로 처리하게 할 때 씁니다. `.github/skills/<스킬 이름>/SKILL.md`로 만드세요.

```markdown
---
name: team-faq
description: "팀 FAQ 문서를 근거로 질문에 답합니다. 사용자가 팀 규정, 절차, 담당자를 물을 때 사용하세요."
---

# 팀 FAQ 답변

1. `rag search "<질문>" --name <컬렉션> -k 5`로 찾으세요. 명령은 `rag`라는 이름으로, 파이프 없이 실행하세요.
2. 출력된 조각만 근거로 답하고, 없으면 "문서에서 찾지 못했습니다"라고 답하세요.
3. 답 끝에 출처(파일, 제목, 수정일)를 붙이세요.
4. `rag` 명령을 쓸 수 없으면 `docs` 폴더의 파일을 직접 찾아 답하고, 로컬 RAG가 설치되지 않았다고 알리세요.
```

### C. 스크립트에서 검색 결과 쓰기

다른 프로그램이 검색 결과를 쓸 때는 `--json`을 붙인 출력을 읽습니다.
스크립트에서는 PATH의 `rag` 대신 설치 때 등록한 `RAG_HOME`의 Python으로 `rag.py`를 직접 실행하세요. Windows의 `rag.cmd`는 프로그램에서 부르기 까다롭기 때문입니다.
출력이 깨지지 않게 `PYTHONIOENCODING=utf-8`을 함께 넘기세요.

```json
{
  "question": "출장 일비는 얼마야?",
  "notices": ["[docs] 자동 갱신: 0개 파일"],
  "results": [
    {"rank": 1, "similarity": 0.7581, "collection": "docs", "path": "출장 규정.md",
     "file": "C:\\Users\\me\\project\\docs\\출장 규정.md", "title": "출장 규정 > 일비",
     "modified": "2026-11-17 20:46:59", "text": "국내 출장 일비는 하루 3만 원입니다."}
  ]
}
```

Python:

```python
import json, os, subprocess
from pathlib import Path


def rag_search(question, name, k=5):
    home = Path(os.environ["RAG_HOME"])
    python = home / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    result = subprocess.run(
        [str(python), str(home / "rag.py"), "search", question, "--name", name, "-k", str(k), "--json"],
        capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)["results"]
```

Node.js:

```js
const { execFileSync } = require('node:child_process')
const path = require('node:path')

function ragSearch(question, name, k = 5) {
  const home = process.env.RAG_HOME
  const python = path.join(home, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
  const output = execFileSync(python, [path.join(home, 'rag.py'), 'search', question, '--name', name, '-k', String(k), '--json'], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  })
  return JSON.parse(output).results
}
```

## 지킬 것

- 컬렉션 이름은 `rag scan`의 "제안 이름"을 쓰세요. 다른 프로젝트의 `docs`가 이미 있으면 `<상위 폴더 이름>-docs`처럼 겹치지 않는 이름이 제안됩니다.
- 검색 결과는 Copilot 대화로 전달되므로, Copilot에 보내면 안 되는 문서는 컬렉션으로 만들지 마세요.
- 예제나 프로젝트의 README에는 사람이 할 일을 "Copilot에게 이렇게 요청하세요" 형태로 쓰고, 터미널 명령을 직접 입력하라고 쓰지 마세요.
