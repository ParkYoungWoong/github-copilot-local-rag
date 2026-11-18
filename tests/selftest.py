#!/usr/bin/env python3
"""local-rag 자체 시험.

임시 폴더에 시험용 문서와 색인을 만들어 rag 명령을 끝까지 돌려 보고, 끝나면 모두 지운다.
실제 색인(indexes 폴더)은 건드리지 않는다. Ollama와 임베딩 모델이 있어야 한다.
마지막 묶음(경로 계산)은 Ollama 없이 돌며, Windows 경로도 문자열로 확인한다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "setup"))
import kit  # noqa: E402
import rag  # noqa: E402

LAUNCHER = KIT / "bin" / ("rag.cmd" if os.name == "nt" else "rag")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"[{'통과' if ok else '실패'}] {name}" + ("" if ok or not detail else f"\n        {detail}"), flush=True)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Runner:
    def __init__(self, index_dir):
        # 느린 PC에서는 예상 시간이 20초를 넘어 자동 갱신을 건너뛰므로, 시험에서는 한도를 크게 둔다.
        self.env = dict(os.environ, RAG_INDEX_DIR=str(index_dir), RAG_AUTO_REFRESH_LIMIT="100000")

    def __call__(self, *args):
        result = subprocess.run([str(LAUNCHER), *args], env=self.env, capture_output=True, encoding="utf-8", errors="replace")
        return result.returncode, result.stdout + result.stderr

    def json(self, *args):
        code, output = self(*args, "--json")
        try:
            return json.loads(output[output.index("{"):]) if code == 0 else None
        except ValueError:
            return None


def top_file(run, question, name):
    data = run.json("search", question, "--name", name, "-k", "3")
    return data["results"][0]["path"] if data and data["results"] else None


def collection(run, name):
    data = run.json("list")
    for item in (data or {}).get("collections", []):
        if item["name"] == name:
            return item
    return None


def end_to_end(base):
    run = Runner(base / "indexes")
    docs = base / "팀 문서" / "docs-a"
    write(docs / "출장 규정.md", "# 출장 규정\n\n국내 출장 일비는 하루 3만 원입니다. 출장 신청은 출발 3일 전까지 팀장에게 합니다.\n")
    write(docs / unicodedata.normalize("NFD", "휴가 안내.md"), "# 휴가 안내\n\n입사 첫해 연차는 11일입니다. 반차는 오전과 오후로 나누어 씁니다.\n")
    write(docs / "장비 점검.md", "# 장비 점검\n\n온도 센서는 매주 월요일에 교정합니다. 측정 오차가 0.5도를 넘으면 교체합니다.\n\n"
                              "```bash\n# 이 줄은 제목이 아닙니다\necho check\n```\n")
    (docs / "._출장 규정.md").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 60)
    (docs / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    try:
        subprocess.run(["git", "init", "-q", str(docs)], check=False, capture_output=True)
    except OSError:
        pass  # git이 없는 PC에서는 폴더를 직접 훑는 방식으로 시험한다.

    code, scan = run("scan", str(docs))
    found = re.search(r"제안 이름: (\S+)", scan)
    name = found.group(1) if found else "?"
    check("1. scan: 대상 3개, 제안 이름은 '상위 폴더-폴더-해시', 숨은 파일(._, .DS_Store)은 세지 않음",
          code == 0 and "색인 대상: 3개" in scan and re.fullmatch(r"[a-z0-9가-힣-]*docs-a-[0-9a-f]{4}", name) is not None
          and "바이너리" not in scan, scan)
    code, output = run("index", str(docs), "--desc", "시험 문서", "--auto-refresh", "on")
    item = collection(run, name)
    check("2. 새 폴더 index에 --desc, --auto-refresh를 함께 줘도 만들어짐",
          code == 0 and item and item["description"] == "시험 문서" and item["files"] == 3, output)
    estimate = int(scan.split("예상 ")[1].split("개")[0]) if "예상 " in scan else -1
    check("3. scan의 예상 조각 수와 실제 조각 수가 같음", item is not None and item["chunks"] == estimate,
          f"예상 {estimate}, 실제 {item and item['chunks']}")
    answers = {"출장 가면 하루에 얼마 받아?": "출장 규정.md", "신입 사원 연차는 며칠이야?": "휴가 안내.md",
               "센서 교정은 언제 해?": "장비 점검.md"}
    got = {question: top_file(run, question, name) for question in answers}
    check("4. 질문마다 맞는 한글 파일이 1위(NFD로 만든 파일 이름도 NFC로 저장)",
          all(got[q] == a for q, a in answers.items()) and all(unicodedata.is_normalized("NFC", p or "") for p in got.values()),
          json.dumps(got, ensure_ascii=False))
    data = run.json("search", "센서 교정 주기", "--name", name, "-k", "5")
    titles = [result["title"] for result in (data or {}).get("results", [])]
    check("5. 코드 블록 안의 # 줄은 제목으로 보지 않음", data is not None and "이 줄은 제목이 아닙니다" not in " ".join(titles), str(titles))
    check("6. --json 결과에 순위, 유사도, 파일 전체 경로, 안내 문구가 있음",
          data is not None and data["results"] and {"rank", "similarity", "file", "path", "text"} <= set(data["results"][0])
          and isinstance(data["notices"], list), str(data)[:300])

    write(docs / "출장 규정.md", "# 출장 규정\n\n국내 출장 일비는 하루 5만 원으로 올랐습니다. 출장 신청은 출발 3일 전까지 합니다.\n")
    (docs / "장비 점검.md").unlink()
    code, output = run("search", "출장 일비는 얼마야?", "--name", name, "-k", "3")
    check("7. 내용을 바꾸고 하나를 지우면 검색할 때 반영됨",
          code == 0 and "5만 원" in output and "장비 점검.md" not in output and "자동 갱신: 1개 파일, 지운 파일 1개" in output, output)

    moved = docs.parent / "docs-a-옮김"
    docs.rename(moved)
    code, output = run("index", "--name", name)
    item = collection(run, name)
    check("8. 원본 폴더가 없으면 아무것도 지우지 않고 rag move를 안내", item and item["files"] == 2 and "rag move" in output, output)
    code, output = run("search", "연차", "--name", name, "-k", "1")
    check("9. 원본 폴더가 없어도 기존 색인으로 검색하고 rag move를 안내", code == 0 and "휴가 안내.md" in output and "rag move" in output, output)
    other = base / "다른 폴더"
    write(other / "메모.md", "# 메모\n\n회의실 예약은 사내 포털에서 합니다.\n")
    code, output = run("index", str(other), "--name", name)
    check("10. 같은 이름을 다른 폴더에 쓰면 거부하고 rag move와 다른 이름을 안내",
          code != 0 and f"rag move {name}" in output and "--name" in output, output)
    code, preview = run("move", name, str(moved))
    still = collection(run, name)
    check("11. rag move를 --yes 없이 실행하면 미리보기만 함",
          code == 0 and "내용이 같은 파일 2개" in preview and still and Path(still["source"]).name == "docs-a", preview)
    code, output = run("move", name, str(moved), "--yes")
    code2, dry = run("index", "--name", name, "--dry-run")
    check("12. rag move --yes 뒤에는 다시 임베딩할 파일도 지울 파일도 없음",
          code == 0 and "다시 임베딩할 파일: 0개" in dry and "지울 파일: 0개" in dry, output + dry)

    nfd_copy = base / "외장 드라이브 흉내" / "docs-a"
    for path in moved.iterdir():
        if path.is_file():
            target = nfd_copy / unicodedata.normalize("NFD", path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    code, output = run("move", name, str(nfd_copy), "--yes")
    code2, dry = run("index", "--name", name, "--dry-run")
    code3, update = run("index", "--name", name)
    item = collection(run, name)
    check("13. 파일 이름이 NFD로 바뀐 사본으로 옮겨도 중복 없이 그대로 씀",
          "내용이 같은 파일 2개" in output and "다시 임베딩할 파일: 0개" in dry and item and item["files"] == 2, output + dry + update)

    code, output = run("search", "출장 \"일비\" 100% 얼마?", "--name", name, "-k", "1")
    check("14. 한글, 공백, 따옴표, %가 든 질문", code == 0 and "출장 규정.md" in output, output)
    write(nfd_copy / "이모지.md", "# 이모지\n\n축하 메시지에는 🎉 이모지를 씁니다.\n")
    code, output = run("search", "축하 메시지", "--name", name, "-k", "1")
    check("15. CP949에 없는 글자가 든 문서를 파이프로 출력해도 멈추지 않음", code == 0 and "이모지.md" in output, output)

    def existing(name):
        # NTFS는 NFD 이름을 그대로 두므로, 디스크에 있는 이름을 찾아 그 파일을 고친다.
        found = [path for path in nfd_copy.iterdir() if unicodedata.normalize("NFC", path.name) == name]
        return found[0] if found else nfd_copy / name

    write(existing("출장 규정.md"), "# 출장 규정\n\n국내 출장 일비는 하루 6만 원입니다.\n")
    write(existing("이모지.md"), "# 이모지\n\n축하 메시지에는 박수 이모지를 씁니다.\n")
    code, only = run("index", "--name", name, "--only", "출장*", "--dry-run")
    code2, single = run("index", "--name", name, "--file", "이모지.md")
    code3, after = run("index", "--name", name, "--dry-run")
    check("16. --only는 패턴에 맞는 파일만, --file은 지정한 파일만, --dry-run은 저장하지 않음",
          "다시 임베딩할 파일: 1개" in only and "다시 임베딩한 파일: 1개" in single and "다시 임베딩할 파일: 1개" in after,
          only + single + after)
    run("index", "--name", name, "--auto-refresh", "off")
    code, output = run("search", "출장 일비", "--name", name, "-k", "1")
    check("17. 자동 갱신을 끄면 갱신하지 않고 안내만 함", "자동 갱신이 꺼져 있어" in output and "6만 원" not in output, output)
    code, output = run("remove", name)
    check("18. remove를 --yes 없이 실행하면 지우지 않음", collection(run, name) is not None, output)
    code, output = run("remove", name, "--yes")
    check("19. remove --yes는 색인만 지우고 원본은 그대로", collection(run, name) is None and existing("출장 규정.md").exists(), output)


def job_checks(base):
    """AI 도구가 기다리다 먼저 돌아와 같은 색인을 다시 실행하거나, 색인하던 프로세스가 꺼진 경우."""
    import joblock
    index_dir = base / "job-indexes"
    run = Runner(index_dir)
    env = dict(run.env, RAG_TEST_DELAY="1.5")
    docs = base / "작업 시험" / "docs"
    for number, topic in enumerate(["회의실", "주차", "택배", "식당"]):
        write(docs / f"{topic}.md", f"# {topic} 안내\n\n{topic} 이용 시간은 오전 {number + 8}시부터입니다.\n")
    python, script = str(kit.venv_python()), str(KIT / "rag.py")

    other = base / "작업 시험" / "docs-kill"
    for path in docs.iterdir():
        write(other / path.name, path.read_text(encoding="utf-8"))

    def start(name, folder=docs):
        return subprocess.Popen([python, script, "index", str(folder), "--name", name], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")

    def wait_until(condition, seconds=120):
        end = time.time() + seconds
        while time.time() < end and not condition():
            time.sleep(0.2)
        return condition()

    def kill(process):
        if os.name == "nt":  # 가상 환경의 python.exe는 실제 Python을 자식으로 띄우므로 함께 끈다.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            process.kill()
        process.wait()

    jobs = index_dir / ".jobs"
    first = start("job-test")
    ready = wait_until(lambda: joblock.is_running(jobs, "job-test") and (index_dir / "job-test.db").exists())
    code, searched = run("search", "주차 시간", "--name", "job-test", "-k", "1")
    still = joblock.is_running(jobs, "job-test")
    second = subprocess.run([python, script, "index", str(docs), "--name", "job-test"], env=env, capture_output=True,
                            encoding="utf-8", errors="replace")
    out1 = first.communicate()[0]
    out2 = second.stdout + second.stderr
    item = collection(run, "job-test")
    check("32. 색인 중에 검색하면 기다리지 않고 지금까지 만든 색인으로 찾고 그렇다고 알림",
          ready and code == 0 and ("색인하는 중이라" in searched or not still), searched)
    # 두 번째가 늦게 떠서 앞 작업이 이미 끝났으면 그냥 갱신(바뀐 파일 0개)으로 끝나는 것도 맞는 동작이다.
    check("33. 같은 색인을 겹쳐 실행하면 두 번째는 진행 중인 작업에 이어 붙어 결과를 보여 주고, 조각이 두 번 들어가지 않음",
          first.returncode == 0 and second.returncode == 0 and joblock.END_MARK in out2
          and ("진행 중입니다" in out2 or "다시 임베딩한 파일: 0개" in out2)
          and item is not None and item["files"] == 4 and item["chunks"] == 4, out1 + "\n---\n" + out2)

    slow = dict(env, RAG_TEST_DELAY="3")
    holder = subprocess.Popen([python, script, "index", str(other), "--name", "job-kill"], env=slow,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    wait_until(lambda: joblock.is_running(jobs, "job-kill"))
    follower = subprocess.Popen([python, script, "index", str(other), "--name", "job-kill"], env=slow,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    lines = []
    reader = threading.Thread(target=lambda: lines.extend(follower.stdout), daemon=True)
    reader.start()
    attached = wait_until(lambda: any("진행 중입니다" in line for line in lines) or follower.poll() is not None)
    attached = attached and any("진행 중입니다" in line for line in lines) and holder.poll() is None
    if attached:
        kill(holder)
    else:
        holder.wait()
    follower.wait()
    reader.join(10)
    out = "".join(lines)
    item = collection(run, "job-kill")
    check("34. 색인하던 프로세스가 꺼지면, 이어 붙어 있던 쪽이 이어서 끝까지 함",
          follower.returncode == 0 and (not attached or "이어서 진행합니다" in out) and item is not None
          and item["files"] == 4 and item["chunks"] == 4, out)


def pure_checks(base):
    raw = "%USERPROFILE%\\AppData\\Local\\Microsoft\\WindowsApps;C:\\Old\\local-rag\\bin;C:\\Tools"
    value = kit.windows_path_value(raw, "D:\\local-rag\\bin", ["C:\\Old\\local-rag\\bin"])
    again = kit.windows_path_value(value, "D:\\local-rag\\bin", ["C:\\Old\\local-rag\\bin"])
    removed = kit.windows_path_value(value, "", ["D:\\local-rag\\bin"])
    check("20. Windows Path: 옛 경로를 빼고 한 번만 끝에 붙임, 변수는 풀지 않음, 지우기도 됨",
          value == "%USERPROFILE%\\AppData\\Local\\Microsoft\\WindowsApps;C:\\Tools;D:\\local-rag\\bin" and again == value
          and removed == "%USERPROFILE%\\AppData\\Local\\Microsoft\\WindowsApps;C:\\Tools", value)
    nfd = unicodedata.normalize("NFD", "C:/Users/A/문서/")
    check("21. Windows 폴더 비교: 대소문자, 구분자, 끝 구분자, 한글 표기 차이를 무시",
          rag.path_key(nfd, windows=True) == rag.path_key("c:\\users\\a\\문서", windows=True)
          and rag.path_key("/Users/a/문서/", windows=False) == rag.path_key(unicodedata.normalize("NFD", "/Users/a/문서"), windows=False))
    long_path = "C:\\" + "가" * 250 + "\\a.md"
    check("22. Windows 긴 경로와 네트워크 경로에 \\\\?\\ 접두사",
          rag.windows_long_path(long_path).startswith("\\\\?\\C:\\") and rag.windows_long_path("C:\\short.md") == "C:\\short.md"
          and rag.windows_long_path("\\\\server\\share\\" + "a" * 250).startswith("\\\\?\\UNC\\server\\share\\"))
    check("23. Windows 드라이브 구분(외장 드라이브 판단)",
          kit.windows_drive("E:\\local-rag") == "e:" and kit.windows_drive("\\\\nas\\team\\docs") == "\\\\nas\\team"
          and kit.windows_drive("C:\\Users\\a") != kit.windows_drive("E:\\local-rag"))
    block = kit.shell_block(PurePosixPath("/Users/a/내 폴더/it's"))
    text = kit.text_with_block("export A=1\n", block)
    replaced = kit.text_with_block(text, kit.shell_block(PurePosixPath("/Users/a/new")))
    check("24. 셸 설정 파일 묶음: 붙이기, 바꾸기, 지우기, 공백과 작은따옴표가 든 경로",
          text.count(kit.BLOCK_START) == 1 and "'/Users/a/내 폴더/it'\"'\"'s'" in text and "/Users/a/new" in replaced
          and replaced.count(kit.BLOCK_START) == 1 and kit.text_with_block(replaced, "") == "export A=1\n\n", text)
    jsonc = ('{\n    // 내 설정\n    "editor.fontSize": 14,\n    "chat.tools.terminal.autoApprove": {\n'
             '        "/^npm test$/": true,\n        "/^rag remove( |$)/": true, // 내가 바꾼 값\n    },\n}\n')
    new_text = kit.settings_with_rules(jsonc)
    parsed = kit.jsonc_loads(new_text)
    rules = parsed["chat.tools.terminal.autoApprove"]
    check("25. VS Code 설정(주석, 끝 쉼표 있음)에 규칙을 넣어도 주석과 내 값은 그대로",
          "// 내 설정" in new_text and "// 내가 바꾼 값" in new_text and rules["/^rag remove( |$)/"] is True
          and rules["/^npm test$/"] is True and rules["/^rag (search|list|scan|check)( |$)/"] is True
          and kit.settings_with_rules(new_text) == new_text, new_text)
    empty = kit.jsonc_loads(kit.settings_with_rules(""))
    plain = kit.jsonc_loads(kit.settings_with_rules('{"a": 1}'))
    check("26. 빈 설정 파일과 규칙이 없는 설정에도 넣음",
          len(empty["chat.tools.terminal.autoApprove"]) == len(kit.APPROVE_RULES) and plain["a"] == 1
          and len(plain["chat.tools.terminal.autoApprove"]) == len(kit.APPROVE_RULES))
    names = [path.name for path in (KIT / "offline" / "wheels").glob("*.whl") if not path.name.startswith("._")]
    expected = [("windows", "amd64"), ("mac", "arm64"), ("mac", "x86_64"), ("linux", "x86_64"), ("linux", "aarch64")]
    picked = {pair: [name for name in names if kit.wheel_tag_matches(name, *pair)] for pair in expected}
    check("27. 반입용 sqlite-vec 파일이 운영체제마다 정확히 하나씩 있음", all(len(found) == 1 for found in picked.values()),
          json.dumps({f"{a}-{b}": c for (a, b), c in picked.items()}, ensure_ascii=False))

    project = base / "내 프로젝트"
    (project / ".git").mkdir(parents=True)
    (project / "docs" / "규정").mkdir(parents=True)
    other_project = base / "다른 곳" / "내 프로젝트"
    (other_project / "AGENTS.md").parent.mkdir(parents=True)
    (other_project / "AGENTS.md").write_text("# 안내\n", encoding="utf-8")
    (other_project / "docs").mkdir()
    first, again = rag.suggest_name(project / "docs"), rag.suggest_name(project / "docs")
    second, nested = rag.suggest_name(other_project / "docs"), rag.suggest_name(project / "docs" / "규정")
    check("28. 컬렉션 이름: 프로젝트-폴더-해시, 같은 폴더는 같은 이름, 이름이 같은 다른 프로젝트와 겹치지 않음",
          re.fullmatch(r"내-프로젝트-docs-[0-9a-f]{4}", first) is not None and first == again and second != first
          and second.startswith("내-프로젝트-docs-") and re.fullmatch(r"내-프로젝트-docs-규정-[0-9a-f]{4}", nested) is not None,
          f"{first} {second} {nested}")
    gemma = rag.embedding_text("출장 규정.md", "일비", "하루 3만 원 {text}", "embeddinggemma:300m")
    qwen = rag.embedding_text("출장 규정.md", "일비", "하루 3만 원", "qwen3-embedding:0.6b")
    query = rag.fill(rag.model_profile("embeddinggemma:300m")["query"], {"question": "일비는?"})
    unknown = rag.model_profile("some-model:latest")
    check("29. 모델마다 문서, 질문 형식(목록에 없는 모델은 형식 없이), 본문의 중괄호는 그대로",
          gemma == "title: 출장 규정.md > 일비 | text: 하루 3만 원 {text}" and qwen == "출장 규정.md > 일비\n하루 3만 원"
          and query == "task: search result | query: 일비는?" and unknown["query"] == "{question}", f"{gemma!r} {qwen!r} {query!r}")
    block, inside = [], False
    for line in (KIT / "bin" / "rag.cmd").read_text(encoding="utf-8").splitlines():
        if line.strip().endswith("("):
            inside = True
            continue
        if inside and line.strip() == ")":
            inside = False
            continue
        if inside:
            block.append(line)
    check("30. rag.cmd의 if 묶음 안에 괄호가 없음(괄호가 있으면 Windows에서 모든 rag 명령이 문법 오류로 멈춤)",
          block and not any("(" in line or ")" in line for line in block), "\n".join(block))
    section = kit.machine_section(PureWindowsPath("C:/Users/학생/local-rag") if os.name == "nt" else Path("/Users/a/local-rag"))
    check("31. 설치한 스킬에 붙이는 이 PC의 rag 실행 파일 절(전체 경로, 키트 폴더)",
          kit.MACHINE_HEADING in section and "키트 폴더: `" in section and ("rag.cmd" in section if os.name == "nt" else "/bin/rag" in section),
          section)


def main():
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure") and not os.environ.get("PYTHONIOENCODING") and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
    only_pure = "--pure" in sys.argv
    print("local-rag 자체 시험", flush=True)
    base = Path(tempfile.mkdtemp(prefix="local-rag-selftest-"))
    try:
        if not only_pure:
            end_to_end(base)
            job_checks(base)
        pure_checks(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\n결과: {len(RESULTS) - failed}개 통과, {failed}개 실패", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
