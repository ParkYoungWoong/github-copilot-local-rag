#!/usr/bin/env python3
"""local-rag 자체 시험.

임시 폴더에 시험용 문서와 색인을 만들어 rag 명령을 끝까지 돌려 보고, 끝나면 모두 지운다.
실제 색인(indexes 폴더)은 건드리지 않는다. Ollama와 임베딩 모델이 있어야 한다.
마지막 묶음(경로 계산)은 Ollama 없이 돌며, Windows 경로도 문자열로 확인한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

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
        self.env = dict(os.environ, RAG_INDEX_DIR=str(index_dir))

    def __call__(self, *args):
        result = subprocess.run([str(LAUNCHER), *args], env=self.env, capture_output=True, text=True, errors="replace")
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
    check("1. scan: 대상 3개, 제안 이름 docs-a, 숨은 파일(._, .DS_Store)은 세지 않음",
          code == 0 and "색인 대상: 3개" in scan and "제안 이름: docs-a" in scan and "바이너리" not in scan, scan)
    code, output = run("index", str(docs), "--desc", "시험 문서", "--auto-refresh", "on")
    item = collection(run, "docs-a")
    check("2. 새 폴더 index에 --desc, --auto-refresh를 함께 줘도 만들어짐",
          code == 0 and item and item["description"] == "시험 문서" and item["files"] == 3, output)
    estimate = int(scan.split("예상 ")[1].split("개")[0]) if "예상 " in scan else -1
    check("3. scan의 예상 조각 수와 실제 조각 수가 같음", item is not None and item["chunks"] == estimate,
          f"예상 {estimate}, 실제 {item and item['chunks']}")
    answers = {"출장 가면 하루에 얼마 받아?": "출장 규정.md", "신입 사원 연차는 며칠이야?": "휴가 안내.md",
               "센서 교정은 언제 해?": "장비 점검.md"}
    got = {question: top_file(run, question, "docs-a") for question in answers}
    check("4. 질문마다 맞는 한글 파일이 1위(NFD로 만든 파일 이름도 NFC로 저장)",
          all(got[q] == a for q, a in answers.items()) and all(unicodedata.is_normalized("NFC", p or "") for p in got.values()),
          json.dumps(got, ensure_ascii=False))
    data = run.json("search", "센서 교정 주기", "--name", "docs-a", "-k", "5")
    titles = [result["title"] for result in (data or {}).get("results", [])]
    check("5. 코드 블록 안의 # 줄은 제목으로 보지 않음", data is not None and "이 줄은 제목이 아닙니다" not in " ".join(titles), str(titles))
    check("6. --json 결과에 순위, 유사도, 파일 전체 경로, 안내 문구가 있음",
          data is not None and data["results"] and {"rank", "similarity", "file", "path", "text"} <= set(data["results"][0])
          and isinstance(data["notices"], list), str(data)[:300])

    write(docs / "출장 규정.md", "# 출장 규정\n\n국내 출장 일비는 하루 5만 원으로 올랐습니다. 출장 신청은 출발 3일 전까지 합니다.\n")
    (docs / "장비 점검.md").unlink()
    code, output = run("search", "출장 일비는 얼마야?", "--name", "docs-a", "-k", "3")
    check("7. 내용을 바꾸고 하나를 지우면 검색할 때 반영됨",
          code == 0 and "5만 원" in output and "장비 점검.md" not in output and "자동 갱신: 1개 파일, 지운 파일 1개" in output, output)

    moved = docs.parent / "docs-a-옮김"
    docs.rename(moved)
    code, output = run("index", "--name", "docs-a")
    item = collection(run, "docs-a")
    check("8. 원본 폴더가 없으면 아무것도 지우지 않고 rag move를 안내", item and item["files"] == 2 and "rag move" in output, output)
    code, output = run("search", "연차", "--name", "docs-a", "-k", "1")
    check("9. 원본 폴더가 없어도 기존 색인으로 검색하고 rag move를 안내", code == 0 and "휴가 안내.md" in output and "rag move" in output, output)
    other = base / "다른 폴더"
    write(other / "메모.md", "# 메모\n\n회의실 예약은 사내 포털에서 합니다.\n")
    code, output = run("index", str(other), "--name", "docs-a")
    check("10. 같은 이름을 다른 폴더에 쓰면 거부하고 rag move와 다른 이름을 안내",
          code != 0 and "rag move docs-a" in output and "--name" in output, output)
    code, preview = run("move", "docs-a", str(moved))
    still = collection(run, "docs-a")
    check("11. rag move를 --yes 없이 실행하면 미리보기만 함",
          code == 0 and "내용이 같은 파일 2개" in preview and still and Path(still["source"]).name == "docs-a", preview)
    code, output = run("move", "docs-a", str(moved), "--yes")
    code2, dry = run("index", "--name", "docs-a", "--dry-run")
    check("12. rag move --yes 뒤에는 다시 임베딩할 파일도 지울 파일도 없음",
          code == 0 and "다시 임베딩할 파일: 0개" in dry and "지울 파일: 0개" in dry, output + dry)

    nfd_copy = base / "외장 드라이브 흉내" / "docs-a"
    for path in moved.iterdir():
        if path.is_file():
            target = nfd_copy / unicodedata.normalize("NFD", path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    code, output = run("move", "docs-a", str(nfd_copy), "--yes")
    code2, dry = run("index", "--name", "docs-a", "--dry-run")
    code3, update = run("index", "--name", "docs-a")
    item = collection(run, "docs-a")
    check("13. 파일 이름이 NFD로 바뀐 사본으로 옮겨도 중복 없이 그대로 씀",
          "내용이 같은 파일 2개" in output and "다시 임베딩할 파일: 0개" in dry and item and item["files"] == 2, output + dry + update)

    code, output = run("search", "출장 \"일비\" 100% 얼마?", "--name", "docs-a", "-k", "1")
    check("14. 한글, 공백, 따옴표, %가 든 질문", code == 0 and "출장 규정.md" in output, output)
    write(nfd_copy / "이모지.md", "# 이모지\n\n축하 메시지에는 🎉 이모지를 씁니다.\n")
    code, output = run("search", "축하 메시지", "--name", "docs-a", "-k", "1")
    check("15. CP949에 없는 글자가 든 문서를 파이프로 출력해도 멈추지 않음", code == 0 and "이모지.md" in output, output)

    def existing(name):
        # NTFS는 NFD 이름을 그대로 두므로, 디스크에 있는 이름을 찾아 그 파일을 고친다.
        found = [path for path in nfd_copy.iterdir() if unicodedata.normalize("NFC", path.name) == name]
        return found[0] if found else nfd_copy / name

    write(existing("출장 규정.md"), "# 출장 규정\n\n국내 출장 일비는 하루 6만 원입니다.\n")
    write(existing("이모지.md"), "# 이모지\n\n축하 메시지에는 박수 이모지를 씁니다.\n")
    code, only = run("index", "--name", "docs-a", "--only", "출장*", "--dry-run")
    code2, single = run("index", "--name", "docs-a", "--file", "이모지.md")
    code3, after = run("index", "--name", "docs-a", "--dry-run")
    check("16. --only는 패턴에 맞는 파일만, --file은 지정한 파일만, --dry-run은 저장하지 않음",
          "다시 임베딩할 파일: 1개" in only and "다시 임베딩한 파일: 1개" in single and "다시 임베딩할 파일: 1개" in after,
          only + single + after)
    run("index", "--name", "docs-a", "--auto-refresh", "off")
    code, output = run("search", "출장 일비", "--name", "docs-a", "-k", "1")
    check("17. 자동 갱신을 끄면 갱신하지 않고 안내만 함", "자동 갱신이 꺼져 있어" in output and "6만 원" not in output, output)
    code, output = run("remove", "docs-a")
    check("18. remove를 --yes 없이 실행하면 지우지 않음", collection(run, "docs-a") is not None, output)
    code, output = run("remove", "docs-a", "--yes")
    check("19. remove --yes는 색인만 지우고 원본은 그대로", collection(run, "docs-a") is None and (nfd_copy / "출장 규정.md").exists(), output)


def pure_checks():
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
    block = kit.shell_block(Path("/Users/a/내 폴더/it's"))
    text = kit.text_with_block("export A=1\n", block)
    replaced = kit.text_with_block(text, kit.shell_block(Path("/Users/a/new")))
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
          len(empty["chat.tools.terminal.autoApprove"]) == 3 and plain["a"] == 1 and len(plain["chat.tools.terminal.autoApprove"]) == 3)
    names = [path.name for path in (KIT / "offline" / "wheels").glob("*.whl") if not path.name.startswith("._")]
    expected = [("windows", "amd64"), ("mac", "arm64"), ("mac", "x86_64"), ("linux", "x86_64"), ("linux", "aarch64")]
    picked = {pair: [name for name in names if kit.wheel_tag_matches(name, *pair)] for pair in expected}
    check("27. 반입용 sqlite-vec 파일이 운영체제마다 정확히 하나씩 있음", all(len(found) == 1 for found in picked.values()),
          json.dumps({f"{a}-{b}": c for (a, b), c in picked.items()}, ensure_ascii=False))


def main():
    only_pure = "--pure" in sys.argv
    print("local-rag 자체 시험", flush=True)
    base = Path(tempfile.mkdtemp(prefix="local-rag-selftest-"))
    try:
        if not only_pure:
            end_to_end(base)
        pure_checks()
    finally:
        shutil.rmtree(base, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\n결과: {len(RESULTS) - failed}개 통과, {failed}개 실패", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
