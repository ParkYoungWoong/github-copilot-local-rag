#!/usr/bin/env python3
"""local-rag 설치 도우미.

표준 라이브러리만 쓰므로 이 PC의 어떤 Python으로도 실행할 수 있다.
사람이 직접 실행하지 않고, AI 도구(Copilot, Claude Code, Codex 등)가 AGENTS.md의 절차에 따라 실행한다.

  python setup/kit.py check                    이 PC의 설치 상태 점검
  python setup/kit.py install                  설치 계획만 보여 줌(아무것도 바꾸지 않음)
  python setup/kit.py install --yes            설치
  python setup/kit.py prepare [--os windows,mac]
                                               사내망 반입 재료 받기(인터넷 되는 PC에서)
  python setup/kit.py copy-to <폴더> [--with-indexes]
                                               반입용 복사, 또는 외장 드라이브에서 홈 폴더로 복사
  python setup/kit.py uninstall [--yes]        PATH, RAG_HOME, 스킬 제거(Ollama, 모델, 색인은 남김)
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request
from pathlib import Path


KIT = Path(__file__).resolve().parent.parent
OFFLINE = KIT / "offline"
SKILL_SOURCE = KIT / "skill" / "local-rag"
CONFIG_FILE = KIT / "config.json"
DEFAULT_CONFIG_FILE = KIT / "config.default.json"
INDEX_DIR = KIT / "indexes"
BACKUP_DIR = KIT / "backup"
MODELS_FILE = KIT / "models.json"
FALLBACK_MODEL = "qwen3-embedding:0.6b"
PROGRESS_PAGE = KIT / "progress.html"
SQLITE_VEC_VERSION = "0.1.9"
PYTHON_WINDOWS_VERSION = "3.14.10"
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
BLOCK_START = "# >>> local-rag >>>"
BLOCK_END = "# <<< local-rag <<<"
APPROVE_KEY = "chat.tools.terminal.autoApprove"
APPROVE_RULES = [
    ("/^rag (search|list|scan|check)( |$)/", True),
    ("/^rag index .*--dry-run( |$)/", True),
    ("/^rag models( --json)?$/", True),
    ("/^rag remove( |$)/", False),
]
# Claude Code(~/.claude/settings.json의 permissions.allow)에 넣는 규칙. 읽기만 하는 명령만 넣는다.
CLAUDE_RULES = ["Bash(rag search:*)", "Bash(rag list:*)", "Bash(rag scan:*)", "Bash(rag check:*)", "Bash(rag models)"]
DOWNLOADS = {
    "windows": [
        ("ollama/windows/OllamaSetup.exe", "https://ollama.com/download/OllamaSetup.exe"),
        (f"python/windows/python-{PYTHON_WINDOWS_VERSION}-amd64.exe",
         f"https://www.python.org/ftp/python/{PYTHON_WINDOWS_VERSION}/python-{PYTHON_WINDOWS_VERSION}-amd64.exe"),
    ],
    "mac": [
        ("ollama/mac/Ollama-darwin.zip", "https://ollama.com/download/Ollama-darwin.zip"),
    ],
    "linux": [],
}
# 반입할 때 함께 옮기지 않는 것(PC마다 새로 만드는 것)
COPY_SKIP = {".venv", "__pycache__", ".git", "backup", "config.json", "progress.html"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
INSTALL_STEPS = ["가상 환경과 sqlite-vec", "Ollama", "임베딩 모델", "config.json과 속도 측정", "rag 명령 등록",
                 "AI 도구 스킬", "자동 승인 규칙", "이전 키트 폴더의 색인", "자체 시험"]
PROGRESS = None  # 진행 상황 화면(설치, 반입 준비 중에만)


class KitError(Exception):
    pass


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def say(text=""):
    print(text, flush=True)


def note(text):
    """단계 안의 한 줄. 진행 상황 화면에도 남긴다."""
    if PROGRESS:
        PROGRESS.note(text)
    else:
        say(f"  {text}")


def setup_output():
    """Windows에서 파이프로 읽는 AI 도구는 UTF-8을 기대한다(Python 3.14까지 파이프 출력은 CP949라 깨짐)."""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            if IS_WINDOWS and not os.environ.get("PYTHONIOENCODING") and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            else:
                stream.reconfigure(errors="replace", line_buffering=True)
        except (ValueError, OSError):
            pass


def command_line(*parts):
    """터미널에 그대로 붙여 넣을 수 있는 명령. Windows PowerShell은 따옴표로 시작하는 명령 앞에 &가 필요하다."""
    text = " ".join(f'"{part}"' if (" " in str(part) or not str(part).isascii() or "\\" in str(part) or "/" in str(part))
                    else str(part) for part in parts)
    return ("& " + text) if IS_WINDOWS else text


def current_os():
    return "windows" if IS_WINDOWS else "mac" if IS_MAC else "linux"


def python_machine():
    """지금 Python의 CPU 종류. Windows ARM PC에서 x64 Python을 쓰면 운영체제는 ARM64여도 Python은 amd64다."""
    if IS_WINDOWS:
        tag = sysconfig.get_platform().lower()
        return "amd64" if tag.endswith("amd64") else "arm64" if tag.endswith("arm64") else "x86"
    return platform.machine()


def is_junk(name):
    return name.startswith("._") or name.lower() in JUNK_NAMES


def home():
    return Path.home()


def venv_python(kit=KIT):
    return kit / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary, path)


def ollama_url():
    config = load_json(CONFIG_FILE) or load_json(DEFAULT_CONFIG_FILE) or {}
    return config.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")


def local_request(path, payload=None, timeout=10):
    """이 PC의 Ollama에 요청한다. 회사 프록시를 타지 않는다."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(ollama_url() + path, data=data, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def ollama_running():
    try:
        with local_request("/api/version", timeout=3) as response:
            return json.loads(response.read().decode("utf-8")).get("version", "?")
    except Exception:
        return None


def ollama_models():
    try:
        with local_request("/api/tags", timeout=5) as response:
            return [item.get("name", "") for item in json.loads(response.read().decode("utf-8")).get("models", [])]
    except Exception:
        return None


def wait_for(check, seconds):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(1)
    return check()


def free_bytes(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def internet_ok(url="https://pypi.org/simple/sqlite-vec/"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=6):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def explain_network_error(error, url):
    text = str(error)
    if "CERTIFICATE" in text.upper() or "SSL" in text.upper():
        return (f"인증서 오류로 {url}에 접속하지 못했습니다. 인증서 검증을 끄지 말고, 회사 인증서 설정이 필요한지 "
                "담당 부서에 확인하세요.")
    return (f"{url}에 접속하지 못했습니다({text}). 회사 망에서 막혔다면 인터넷이 되는 PC에서 "
            "'반입 준비해 줘'로 받은 키트 폴더를 가져오세요.")


# ---------------------------------------------------------------------------
# 위치
# ---------------------------------------------------------------------------

SYNC_MARKERS = ("onedrive", "icloud drive", "mobile documents", "dropbox", "google drive", "googledrive")


def windows_drive(path_text):
    """'C:\\a\\b' -> 'c:', UNC 경로 -> '\\\\server\\share'."""
    text = path_text.replace("/", "\\")
    if text.startswith("\\\\"):
        parts = text[2:].split("\\")
        return ("\\\\" + "\\".join(parts[:2])).lower()
    return text[:2].lower() if len(text) > 1 and text[1] == ":" else ""


def location_problems(kit=KIT):
    """키트 폴더 위치에서 문제가 될 만한 점을 돌려준다."""
    problems = []
    lowered = str(kit).lower()
    if any(marker in lowered for marker in SYNC_MARKERS):
        problems.append("동기화 폴더(OneDrive, iCloud Drive 등) 안에 있습니다.")
    if IS_WINDOWS:
        if windows_drive(str(kit)) != windows_drive(str(home())):
            problems.append("홈 폴더와 다른 드라이브(외장 드라이브, 네트워크 드라이브 등)에 있습니다.")
        else:
            try:
                import ctypes
                kind = ctypes.windll.kernel32.GetDriveTypeW(windows_drive(str(kit)) + "\\")
                if kind in (2, 4):
                    problems.append("이동식 드라이브나 네트워크 드라이브에 있습니다.")
            except Exception:
                pass
        if len(str(kit)) > 150:
            problems.append("경로가 너무 깁니다(150자 초과).")
    else:
        try:
            if os.stat(kit).st_dev != os.stat(home()).st_dev:
                problems.append("홈 폴더와 다른 디스크(외장 드라이브 등)에 있습니다.")
        except OSError:
            pass
    try:
        result = subprocess.run(["git", "-C", str(kit), "rev-parse", "--show-toplevel"], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=10)
        top = (result.stdout or "").strip()
        if result.returncode == 0 and top and Path(top).resolve() != kit.resolve():
            problems.append(f"다른 Git 저장소({top}) 안에 있습니다.")
    except (OSError, subprocess.SubprocessError):
        pass
    return problems


def suggested_home_folder():
    return home() / "local-rag"


# ---------------------------------------------------------------------------
# Python과 가상 환경
# ---------------------------------------------------------------------------

def python_problem(executable=None):
    """이 Python으로 설치할 수 있는지 본다. 문제가 없으면 None."""
    version = sys.version_info
    if IS_WINDOWS and "\\windowsapps\\" in sys.executable.lower():
        return ("Microsoft Store의 Python은 설정 파일이 다른 곳에 저장되어 쓸 수 없습니다. "
                "python.org의 Python(반입 재료의 설치 파일)으로 다시 실행하세요.")
    if IS_WINDOWS and sys.maxsize <= 2 ** 32:
        return "32비트 Python입니다. 64비트 Python으로 다시 실행하세요."
    if IS_WINDOWS and python_machine() == "arm64":
        return ("ARM64용 Python입니다. sqlite-vec는 Windows x64 Python용만 있으니 python.org의 Windows x64(amd64) Python으로 "
                "다시 실행하세요(ARM PC에서도 x64 Python이 동작합니다).")
    if executable is None and version < (3, 10):
        return f"이 Python({version.major}.{version.minor})은 너무 오래된 버전입니다. 3.10 이상이 필요합니다."
    connection = sqlite3.connect(":memory:")
    try:
        if not hasattr(connection, "enable_load_extension"):
            if IS_MAC:
                return ("이 Python은 SQLite 확장 불러오기를 지원하지 않습니다(macOS 기본 Python이나 일부 설치 도구로 만든 Python). "
                        "Homebrew Python(brew install python)으로 다시 실행하세요. python.org의 macOS용 Python도 확장을 불러오지 못합니다.")
            return "이 Python은 SQLite 확장 불러오기를 지원하지 않습니다. python.org의 Python으로 다시 실행하세요."
    finally:
        connection.close()
    return None


def venv_state(kit=KIT):
    """가상 환경이 동작하면 sqlite-vec 버전을, 아니면 None을 돌려준다."""
    python = venv_python(kit)
    if not python.exists():
        return None
    code = ("import sqlite3, sqlite_vec; c = sqlite3.connect(':memory:'); c.enable_load_extension(True); "
            "sqlite_vec.load(c); print(c.execute('select vec_version()').fetchone()[0])")
    try:
        result = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def wheel_tag_matches(name, os_name, machine):
    machine = machine.lower()
    if os_name == "windows":
        return "win_amd64" in name and machine in ("amd64", "x86_64")
    if os_name == "mac":
        return "macosx" in name and (("arm64" in name) == (machine == "arm64"))
    if os_name == "linux":
        return "manylinux" in name and (("aarch64" in name) == (machine in ("aarch64", "arm64")))
    return False


def offline_wheel():
    folder = OFFLINE / "wheels"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob(f"sqlite_vec-{SQLITE_VEC_VERSION}-*.whl")):
        if not is_junk(path.name) and wheel_tag_matches(path.name, current_os(), python_machine()):
            return path
    return None


def base_python():
    return getattr(sys, "_base_executable", None) or sys.executable


def make_venv():
    target = KIT / ".venv"
    if target.exists():
        if Path(sys.prefix).resolve() == target.resolve():
            raise KitError("지금 이 폴더의 가상 환경(.venv) Python으로 실행했습니다. 가상 환경 밖의 Python으로 다시 실행하세요.")
        say("  기존 가상 환경이 이 PC에서 동작하지 않아 새로 만듭니다.")
        try:
            shutil.rmtree(target)
        except OSError as error:
            raise KitError(f"기존 가상 환경을 지우지 못했습니다({error}). AI 도구(VS Code 등)를 완전히 종료했다가 다시 열고 다시 요청하세요.") from error
    subprocess.run([base_python(), "-m", "venv", str(target)], check=True)
    python = str(venv_python())
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    wheel = offline_wheel()
    if wheel:
        say(f"  sqlite-vec를 반입 파일로 설치합니다: {wheel.name}")
        subprocess.run([python, "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True, env=env)
    else:
        if IS_WINDOWS and python_machine() != "amd64":
            raise KitError("sqlite-vec는 Windows x64 Python용만 있습니다. python.org의 Windows x64 Python으로 다시 실행하세요.")
        say(f"  이 PC에 맞는 반입 파일이 없어 인터넷에서 sqlite-vec {SQLITE_VEC_VERSION}을 받습니다.")
        result = subprocess.run([python, "-m", "pip", "install", f"sqlite-vec=={SQLITE_VEC_VERSION}"], env=env)
        if result.returncode != 0:
            raise KitError("sqlite-vec를 받지 못했습니다. 회사 망이면 사내 pip 미러를 쓰거나, 인터넷이 되는 PC에서 "
                           "'반입 준비해 줘'로 받은 폴더를 가져오세요.")
    version = venv_state()
    if not version:
        raise KitError("sqlite-vec를 설치했지만 불러오지 못했습니다. 보안 정책이 확장 파일(.dll, .dylib)을 막았을 수 있습니다. "
                       "담당 부서에 확인하세요.")
    return version


# ---------------------------------------------------------------------------
# Ollama와 모델
# ---------------------------------------------------------------------------

def windows_ollama_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(home() / "AppData" / "Local"))) / "Programs" / "Ollama"


def find_ollama_app():
    if IS_WINDOWS:
        app = windows_ollama_dir() / "ollama app.exe"
        return app if app.exists() else None
    if IS_MAC:
        for folder in (Path("/Applications"), home() / "Applications"):
            if (folder / "Ollama.app").exists():
                return folder / "Ollama.app"
    return None


def start_ollama_app(app):
    if IS_WINDOWS:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(app)], creationflags=flags, close_fds=True)
    elif IS_MAC:
        subprocess.run(["open", str(app)], check=False)


def start_ollama_server(app):
    """앱 대신 Ollama 서버를 바로 실행한다(앱이 응답하지 않을 때만).

    macOS: Ollama 앱은 처음 실행할 때 서버를 띄우기 전에 'Move to Applications?' 창(응용 프로그램 폴더 밖일 때)과
    명령줄 도구 설치용 암호 창을 띄우고 답을 기다린다. AI 도구에서 설치하면 이 창을 못 보고 멈출 수 있어 앱을 닫는다.
    Windows: 보안 프로그램이나 화면 없는 세션 때문에 트레이 앱이 뜨지 않으면 같은 폴더의 ollama.exe를 쓴다.
    나중에 Ollama 앱을 실행하면 앱이 이 서버를 끄고 자기 서버로 바꾼다.
    """
    if IS_MAC:
        binary = app / "Contents" / "Resources" / "ollama"
    elif IS_WINDOWS:
        binary = app.parent / "ollama.exe"
    else:
        return False
    if not binary.is_file():
        return False
    log = home() / ".ollama" / "logs" / "local-rag-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        if IS_MAC:
            subprocess.run(["pkill", "-f", str(app / "Contents" / "MacOS")], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen([str(binary), "serve"], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                             start_new_session=True, close_fds=True)
        else:
            flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            subprocess.Popen([str(binary), "serve"], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                             creationflags=flags, close_fds=True)
    return True


def bring_up_ollama(app, seconds):
    """Ollama 앱을 실행하고 응답할 때까지 기다린다. 앱이 응답하지 않으면 서버를 바로 실행한다."""
    start_ollama_app(app)
    # macOS는 사용자가 확인 창에 답할 시간으로 60초
    if wait_for(ollama_running, 60 if IS_MAC else seconds):
        return True
    if start_ollama_server(app):
        where = "응용 프로그램 폴더" if IS_MAC else "시작 메뉴"
        reason = "확인 창에서 멈춰 있어" if IS_MAC else "응답하지 않아"
        note(f"Ollama 앱이 {reason} 앱 대신 Ollama 서버를 바로 실행했습니다. "
             f"PC를 다시 켠 뒤에는 {where}에서 Ollama를 한 번 실행하세요.")
        return wait_for(ollama_running, 30)
    return False


def offline_file(relative):
    path = OFFLINE / relative
    return path if path.is_file() and path.stat().st_size > 0 else None


def install_ollama():
    """반입한 설치 파일(없으면 인터넷)로 Ollama를 설치한다. 관리자 권한을 쓰지 않는다."""
    system = current_os()
    if system == "linux":
        raise KitError("Linux에서는 https://ollama.com/download 의 안내대로 Ollama를 설치한 뒤 다시 요청하세요.")
    relative = "ollama/windows/OllamaSetup.exe" if IS_WINDOWS else "ollama/mac/Ollama-darwin.zip"
    installer = offline_file(relative)
    if installer is None:
        url = dict(DOWNLOADS[system])[relative] if relative in dict(DOWNLOADS[system]) else None
        if not url or not internet_ok(url):
            raise KitError("Ollama 설치 파일이 없고 인터넷에도 접속하지 못했습니다. 인터넷이 되는 PC에서 "
                           "'반입 준비해 줘'로 받은 키트 폴더를 가져오세요.")
        installer = download(url, OFFLINE / relative)
    if IS_WINDOWS:
        if free_bytes(windows_ollama_dir()) < 5 * 1024 ** 3:
            raise KitError("Ollama를 설치하려면 C 드라이브에 5GB 이상 여유 공간이 필요합니다.")
        marker = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "upgraded"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        say("  Ollama를 설치합니다(관리자 권한 없이, 몇 분 걸릴 수 있음).")
        process = subprocess.Popen([str(installer), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"])
        if process.wait() != 0:
            raise KitError(f"Ollama 설치 파일이 오류로 끝났습니다(종료 코드 {process.returncode}). "
                           f"파일 탐색기에서 {installer}를 직접 실행해 설치한 뒤 다시 요청하세요.")
    else:
        # 응용 프로그램 폴더에 쓸 수 있으면 그곳에 둔다. 다른 곳에 두면 Ollama가 실행할 때마다 옮길지 묻는다.
        target = Path("/Applications") if os.access("/Applications", os.W_OK) else home() / "Applications"
        target.mkdir(exist_ok=True)
        say(f"  Ollama 앱을 {target}에 풉니다(관리자 권한 없이).")
        subprocess.run(["ditto", "-x", "-k", str(installer), str(target)], check=True)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target / "Ollama.app")], check=False)
    app = find_ollama_app()
    if app is None:
        raise KitError("Ollama를 설치했지만 앱을 찾지 못했습니다. 직접 설치 파일을 실행한 뒤 다시 요청하세요.")
    if not wait_for(ollama_running, 20) and not bring_up_ollama(app, 90):
        raise KitError("Ollama 앱이 응답하지 않습니다. Windows는 시작 메뉴, macOS는 응용 프로그램에서 Ollama를 실행한 뒤 다시 요청하세요.")


def windows_registry_value(name):
    if not IS_WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def ollama_models_dir():
    value = os.environ.get("OLLAMA_MODELS") or windows_registry_value("OLLAMA_MODELS")
    return Path(os.path.expandvars(value)).expanduser() if value else home() / ".ollama" / "models"


def normalize_model(model):
    """Ollama는 태그 없는 이름을 '<이름>:latest'로 저장한다."""
    model = (model or "").strip()
    return model if not model or ":" in model.rsplit("/", 1)[-1] else model + ":latest"


def model_catalog():
    data = load_json(MODELS_FILE) or {}
    return data.get("models", []), data.get("default") or FALLBACK_MODEL


def catalog_entry(model):
    return next((item for item in model_catalog()[0] if item.get("name") == model), None)


def default_model():
    """config.json의 기본 모델. 아직 없으면 반입 준비 때 고른 기본 모델, 그것도 없으면 models.json의 기본."""
    configured = (load_json(CONFIG_FILE) or {}).get("embed_model")
    if configured:
        return configured
    carried = (load_json(OFFLINE / "MANIFEST.json") or {}).get("default_model")
    if carried and model_files(OFFLINE / "models", carried):
        return carried
    return model_catalog()[1]


def model_label(model):
    entry = catalog_entry(model)
    return f"{model}({entry['maker']}, {entry['country']}, 약 {entry['size_mb']}MB)" if entry else model


def model_parts(model):
    name, _, tag = model.partition(":")
    namespace, _, short = name.rpartition("/")
    return namespace or "library", short, tag or "latest"


def manifest_path(models_dir, model):
    namespace, short, tag = model_parts(model)
    return Path(models_dir) / "manifests" / "registry.ollama.ai" / namespace / short / tag


def model_files(models_dir, model):
    """모델 폴더에서 이 모델의 manifest와 blob 파일 목록을 돌려준다."""
    manifest = manifest_path(models_dir, model)
    data = load_json(manifest)
    if not data:
        return None
    digests = [data["config"]["digest"]] + [layer["digest"] for layer in data.get("layers", [])]
    blobs = [Path(models_dir) / "blobs" / digest.replace(":", "-") for digest in digests]
    return manifest, blobs


def offline_models():
    """offline/models에 반입해 둔 모델 이름."""
    root = OFFLINE / "models" / "manifests" / "registry.ollama.ai"
    found = []
    if root.is_dir():
        for manifest in sorted(root.glob("*/*/*")):
            if manifest.is_file() and not is_junk(manifest.name):
                namespace, short, tag = manifest.parts[-3:]
                name = f"{short}:{tag}" if namespace == "library" else f"{namespace}/{short}:{tag}"
                if model_files(OFFLINE / "models", name):
                    found.append(name)
    return found


def copy_model(source_dir, target_dir, model, verify=True):
    """manifest와 blob을 복사한다. blob 이름이 곧 sha256이므로 복사한 뒤 내용을 검사한다."""
    found = model_files(source_dir, model)
    if not found:
        raise KitError(f"{source_dir}에 {model} 모델 파일이 없습니다.")
    manifest, blobs = found
    need = sum(blob.stat().st_size for blob in blobs)
    if free_bytes(target_dir) < need + 200 * 1024 ** 2:
        raise KitError(f"모델을 복사할 공간이 부족합니다(약 {need / 1024 ** 3:.1f}GB 필요): {target_dir}")
    (Path(target_dir) / "blobs").mkdir(parents=True, exist_ok=True)
    done = 0
    for blob in blobs:
        target = Path(target_dir) / "blobs" / blob.name
        if not (target.exists() and target.stat().st_size == blob.stat().st_size):
            shutil.copyfile(blob, target)
        if verify and file_sha256(target) != blob.name.split("-", 1)[1]:
            target.unlink(missing_ok=True)
            raise KitError(f"모델 파일이 손상됐습니다: {blob.name}. 반입 재료를 다시 복사하세요.")
        done += blob.stat().st_size
        if PROGRESS:
            PROGRESS.update(done, need, f"{model} 복사 {done / 1024 ** 2:,.0f}MB / {need / 1024 ** 2:,.0f}MB")
    target_manifest = manifest_path(target_dir, model)
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest, target_manifest)


def download_model_from_registry(target_dir, model):
    """Ollama 없이 모델 저장소(registry.ollama.ai)에서 manifest와 blob을 직접 받는다. 받은 뒤 내용을 검사한다."""
    target_dir = Path(target_dir)
    namespace, short, tag = model_parts(model)
    base = f"https://registry.ollama.ai/v2/{namespace}/{short}"
    accept = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
    url = f"{base}/manifests/{tag}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=accept), timeout=60) as response:
            manifest_bytes = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise KitError(f"모델 저장소에 {model} 모델이 없습니다. 이름과 태그(예: embeddinggemma:300m)를 확인하세요.") from error
        raise KitError(explain_network_error(error, url)) from error
    except urllib.error.URLError as error:
        raise KitError(explain_network_error(error, url)) from error
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    digests = [manifest["config"]["digest"]] + [layer["digest"] for layer in manifest.get("layers", [])]
    for digest in digests:
        blob = target_dir / "blobs" / digest.replace(":", "-")
        if blob.is_file() and file_sha256(blob) == digest.split(":", 1)[1]:
            continue
        download(f"{base}/blobs/{digest}", blob, label=f"{model} 모델 파일")
        if file_sha256(blob) != digest.split(":", 1)[1]:
            blob.unlink(missing_ok=True)
            raise KitError(f"받은 모델 파일의 해시가 다릅니다: {digest}. 다시 요청하세요.")
    path = manifest_path(target_dir, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(manifest_bytes)


def pull_model(model):
    entry = catalog_entry(model)
    note(f"인터넷에서 {model} 모델을 받습니다" + (f"(약 {entry['size_mb']}MB)." if entry else "."))
    try:
        with local_request("/api/pull", {"model": model, "stream": True}, timeout=3600) as response:
            for line in response:
                item = json.loads(line.decode("utf-8") or "{}")
                if item.get("error"):
                    if "file does not exist" in item["error"] or "not found" in item["error"]:
                        raise KitError(f"모델 저장소에 {model} 모델이 없습니다. 이름이 맞는지 `rag models`의 목록과 비교해 보세요.")
                    raise KitError(f"{model} 모델을 받지 못했습니다: {item['error']}")
                total, done = item.get("total"), item.get("completed")
                if total and done and PROGRESS:
                    PROGRESS.update(done, total, f"{model} 받는 중 {done / 1024 ** 2:,.0f}MB / {total / 1024 ** 2:,.0f}MB")
    except (urllib.error.URLError, OSError) as error:
        raise KitError(f"{model} 모델을 받지 못했습니다: {error}") from error


def ensure_model(model):
    if model in (ollama_models() or []):
        return "이미 있음"
    if model_files(OFFLINE / "models", model):
        target = ollama_models_dir()
        note(f"반입한 {model} 모델 파일을 Ollama 모델 폴더로 복사합니다: {target}")
        copy_model(OFFLINE / "models", target, model)
        if wait_for(lambda: model in (ollama_models() or []), 30):
            return "반입 파일에서 복사"
        raise KitError("모델 파일을 복사했지만 Ollama가 모델을 찾지 못했습니다. Ollama 앱을 종료했다가 다시 실행한 뒤 다시 요청하세요.")
    pull_model(model)
    if model not in (ollama_models() or []):
        raise KitError(f"{model} 모델을 받지 못했습니다. 회사 망이면 인터넷이 되는 PC에서 '반입 준비해 줘'로 받은 폴더를 가져오세요.")
    return "인터넷에서 받음"


def collection_models(index_dir=INDEX_DIR):
    """컬렉션마다 만들 때 쓴 모델."""
    found = {}
    for path in sorted(Path(index_dir).glob("*.db")) if Path(index_dir).is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                model = dict(connection.execute("SELECT key, value FROM metadata").fetchall()).get("model")
            finally:
                connection.close()
        except sqlite3.Error:
            continue
        if model:
            found.setdefault(model, []).append(path.stem)
    return found


def needed_models(chosen=None):
    """설치할 때 준비할 모델: 기본 모델, 컬렉션이 쓰는 모델, 반입해 온 모델."""
    models = [chosen or default_model()]
    for model in list(collection_models()) + offline_models():
        if model not in models:
            models.append(model)
    return models


def measure_speed(config, model):
    """한글 문단 16개를 한 번에 임베딩해서 이 PC의 초당 조각 수를 잰다."""
    paragraph = ("사내 문서 검색 속도를 재기 위한 시험 문단입니다. 장비 점검 기준과 보고 절차, 담당자 배정 규칙을 설명합니다. " * 12)[:900]
    payload = {"model": model, "keep_alive": config["keep_alive"], "options": {"num_ctx": config["num_ctx"]}}
    try:
        with local_request("/api/embed", dict(payload, input=["준비"]), timeout=300) as response:
            dimension = len(json.loads(response.read().decode("utf-8"))["embeddings"][0])
        started = time.time()
        with local_request("/api/embed", dict(payload, input=[paragraph] * 16), timeout=600) as response:
            json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise KitError(f"{model} 모델로 임베딩하지 못했습니다(Ollama 오류 {error.code}). 임베딩 모델이 맞는지, 받아 둔 모델인지 확인하세요.") from error
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as error:
        raise KitError(f"{model} 모델로 속도를 재지 못했습니다({error}). Ollama가 켜져 있는지 확인하세요.") from error
    return round(16 / max(time.time() - started, 0.001), 3), dimension


def write_config(model=None, measure=()):
    """config.json을 만든다. 기본 모델과, 잰 모델마다의 속도를 저장한다."""
    config = load_json(DEFAULT_CONFIG_FILE)
    if not config:
        raise KitError("config.default.json이 없습니다. 키트를 다시 받으세요.")
    current = load_json(CONFIG_FILE) or {}
    if current.get("ollama_url"):
        config["ollama_url"] = current["ollama_url"]
    config["embed_model"] = model or current.get("embed_model") or model_catalog()[1]
    speeds = dict(current.get("model_speeds") or {})
    results = {}
    for name in dict.fromkeys([config["embed_model"], *measure]):
        speeds[name], dimension = measure_speed(config, name)
        results[name] = (speeds[name], dimension)
    config["model_speeds"] = speeds
    config["embed_chunks_per_sec"] = speeds[config["embed_model"]]
    save_json(CONFIG_FILE, config)
    return config["embed_model"], results


# ---------------------------------------------------------------------------
# PATH와 RAG_HOME
# ---------------------------------------------------------------------------

def shell_quote(text):
    return "'" + text.replace("'", "'\"'\"'") + "'"


def shell_block(kit):
    return (f"{BLOCK_START}\nexport RAG_HOME={shell_quote(str(kit))}\n"
            f"export PATH=\"$RAG_HOME/bin:$PATH\"\n{BLOCK_END}\n")


def text_with_block(text, block):
    """설정 파일에서 local-rag 묶음을 바꾸거나 끝에 붙인다. block이 빈 문자열이면 묶음을 지운다."""
    pattern = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    if not block:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + block


def shell_rc_file():
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return home() / ".zshrc"
    if "bash" in shell:
        return home() / (".bash_profile" if IS_MAC else ".bashrc")
    return home() / ".profile"


def windows_path_value(raw, bin_dir, remove=(), expand=lambda text: text):
    """사용자 Path 원래 값(변수를 풀지 않은 값)에서 옛 local-rag 경로를 빼고 bin_dir을 끝에 한 번만 붙인다.
    bin_dir이 빈 문자열이면 빼기만 한다."""
    def norm(text):
        return expand(text.strip().strip('"')).rstrip("\\/").lower()
    targets = {norm(item) for item in (bin_dir, *remove) if item}
    parts = [part for part in raw.split(";") if part.strip() and norm(part) not in targets]
    if bin_dir:
        parts.append(bin_dir)
    return ";".join(parts)


def broadcast_environment_change():
    try:
        import ctypes
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
    except Exception:
        pass


def set_windows_environment(kit, remove_only=False):
    import winreg
    bin_dir = str(kit / "bin")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            raw, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            raw, kind = "", winreg.REG_EXPAND_SZ
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            kind = winreg.REG_EXPAND_SZ
        try:
            old_home = winreg.QueryValueEx(key, "RAG_HOME")[0]
        except FileNotFoundError:
            old_home = ""
        remove = [old_home.rstrip("\\") + "\\bin"] if old_home else []
        value = windows_path_value(raw, "" if remove_only else bin_dir, remove + ([bin_dir] if remove_only else []),
                                   os.path.expandvars)
        if value != raw:
            winreg.SetValueEx(key, "Path", 0, kind, value)
        if remove_only:
            try:
                winreg.DeleteValue(key, "RAG_HOME")
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, "RAG_HOME", 0, winreg.REG_SZ, str(kit))
    broadcast_environment_change()


def path_configured(kit=KIT):
    if IS_WINDOWS:
        raw = windows_registry_value("Path") or ""
        bin_dir = str(kit / "bin").rstrip("\\").lower()
        return any(os.path.expandvars(part.strip().strip('"')).rstrip("\\").lower() == bin_dir for part in raw.split(";"))
    rc = shell_rc_file()
    try:
        return shell_block(kit) in rc.read_text(encoding="utf-8")
    except OSError:
        return False


def configure_path(kit=KIT, remove_only=False):
    if IS_WINDOWS:
        set_windows_environment(kit, remove_only)
        return "사용자 환경 변수 Path, RAG_HOME"
    rc = shell_rc_file()
    text = rc.read_text(encoding="utf-8") if rc.exists() else ""
    new_text = text_with_block(text, "" if remove_only else shell_block(kit))
    if new_text != text:
        if rc.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(rc, BACKUP_DIR / f"{rc.name.lstrip('.')}-{timestamp()}")
        rc.write_text(new_text, encoding="utf-8")
    bin_file = kit / "bin" / "rag"
    if bin_file.exists():
        bin_file.chmod(bin_file.stat().st_mode | 0o111)
    return str(rc)


# ---------------------------------------------------------------------------
# 스킬(여러 AI 도구가 읽는 개인 스킬 폴더에 같은 내용을 넣는다)
# ---------------------------------------------------------------------------

# ~/.agents/skills: VS Code Copilot, Copilot CLI, Codex, Gemini CLI 등이 함께 읽는 공용 폴더
# ~/.claude/skills: Claude Code
# ~/.copilot/skills: GitHub Copilot(VS Code, Copilot CLI)
SKILL_HOMES = ((".agents", "공용(Copilot, Codex, Gemini 등)"), (".claude", "Claude Code"), (".copilot", "GitHub Copilot"))
MACHINE_HEADING = "## 이 PC의 rag 실행 파일"


def skill_targets():
    return [home() / folder / "skills" / "local-rag" for folder, _ in SKILL_HOMES]


def skill_target():
    return skill_targets()[0]


def skill_files():
    return sorted(path for path in SKILL_SOURCE.rglob("*") if path.is_file() and not is_junk(path.name))


def launcher(kit=KIT):
    return kit / "bin" / ("rag.cmd" if IS_WINDOWS else "rag")


def git_bash_path(path):
    text = str(path).replace("\\", "/")
    return "/" + text[0].lower() + text[2:] if len(text) > 1 and text[1] == ":" else text


def machine_section(kit=KIT):
    """설치한 스킬의 SKILL.md 끝에 붙이는 이 PC 전용 절. rag가 PATH에 없을 때 쓸 전체 경로를 적는다."""
    if IS_WINDOWS:
        ways = [f'- PowerShell: `& "{launcher(kit)}" list`',
                f'- 명령 프롬프트(cmd): `"{launcher(kit)}" list`',
                f'- Git Bash: `"{git_bash_path(kit / "bin" / "rag")}" list`']
    else:
        ways = [f'- `"{launcher(kit)}" list`']
    return (f"\n{MACHINE_HEADING}\n\n"
            "설치 도우미가 이 PC에 맞춰 붙인 절입니다.\n"
            "`rag`를 찾지 못한다는 오류(`command not found`, `인식되지 않습니다`, `is not recognized`)가 나면, "
            "사용자에게 다시 시작하라고 하기 전에 아래처럼 전체 경로로 같은 명령을 실행하세요. `list` 자리에 원래 실행하려던 내용을 그대로 씁니다.\n\n"
            + "\n".join(ways) + "\n\n"
            f"키트 폴더: `{kit}`\n")


def skill_content(source, kit=KIT):
    data = source.read_bytes()
    if source.relative_to(SKILL_SOURCE).as_posix() == "SKILL.md":
        text = data.decode("utf-8").rstrip("\n") + "\n" + machine_section(kit)
        data = text.encode("utf-8")
    return data


def is_junction(path):
    """Windows 디렉터리 연결(junction). Python 3.12 전에는 Path.is_junction이 없어 속성으로 본다."""
    if not IS_WINDOWS:
        return False
    if hasattr(path, "is_junction"):
        return path.is_junction()
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400) and not path.is_symlink()
    except OSError:
        return False


def is_link(path):
    return path.is_symlink() or is_junction(path)


def remove_link(path):
    if path.is_symlink():
        path.unlink()
    else:
        os.rmdir(path)  # Windows 디렉터리 연결(junction): 가리키는 폴더의 내용은 지우지 않는다.


def same_skill_folder(target):
    """target의 상위 폴더가 원본(~/.agents/skills)과 같은 실제 폴더인지(예: ~/.claude/skills가 ~/.agents/skills를 가리키는 링크)."""
    canonical = skill_targets()[0]
    if target == canonical:
        return False
    try:
        return os.path.samefile(target.parent, canonical.parent)
    except OSError:
        return False


def links_skills():
    """macOS, Linux에서는 ~/.agents의 스킬을 원본으로 두고 나머지는 그 폴더를 가리키는 링크로 만든다
    (skills CLI와 같은 방식). Windows는 링크에 권한이 필요할 수 있어 복사한다."""
    return not IS_WINDOWS


def target_state(target, kit=KIT):
    canonical = skill_targets()[0]
    if same_skill_folder(target):
        return target_state(canonical, kit)
    if is_link(target):
        if links_skills() and target != canonical and target.resolve() == canonical.resolve():
            return target_state(canonical, kit)
        return "링크"
    if not (target / "SKILL.md").is_file():
        return "없음"
    for source in skill_files():
        installed = target / source.relative_to(SKILL_SOURCE)
        if not installed.is_file() or installed.read_bytes() != skill_content(source, kit):
            return "옛 버전"
    return "최신"


def skill_installed_state():
    states = {target_state(target) for target in skill_targets()}
    if states == {"최신"}:
        return "최신"
    return "없음" if states == {"없음"} else "옛 버전"


def installed_kit_paths():
    """설치해 둔 스킬에 적힌 키트 폴더(예전에 다른 폴더에서 설치했는지 확인할 때 쓴다)."""
    found = []
    for target in skill_targets():
        try:
            text = (target / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r"^키트 폴더: `(.+)`$", text, re.M)
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def install_skill():
    lines = []
    canonical = skill_targets()[0]
    for (folder, label), target in zip(SKILL_HOMES, skill_targets()):
        if same_skill_folder(target):
            lines.append(f"{target} ({label}, {canonical.parent}와 같은 폴더)")
            continue
        state = target_state(target)
        want_link = links_skills() and target != canonical
        if state == "최신" and (not want_link or target.is_symlink()):
            lines.append(f"{target} ({label}, 그대로)")
            continue
        if is_link(target):
            remove_link(target)  # 링크만 지운다. 가리키던 폴더의 내용은 그대로다.
        elif target.exists():
            backup = BACKUP_DIR / f"skill-{folder.lstrip('.')}-{timestamp()}"
            shutil.copytree(target, backup)
            shutil.rmtree(target)
        if want_link:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.symlink_to(os.path.relpath(canonical, target.parent), target_is_directory=True)
                lines.append(f"{target} ({label}, {canonical}를 가리키는 링크)")
                continue
            except OSError:
                pass
        for source in skill_files():
            destination = target / source.relative_to(SKILL_SOURCE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(skill_content(source))
        lines.append(f"{target} ({label})")
    return lines


def remove_skills():
    removed = []
    for (folder, _), target in zip(SKILL_HOMES, skill_targets()):
        if same_skill_folder(target):
            continue
        if is_link(target):
            remove_link(target)
            removed.append(str(target))
        elif (target / "SKILL.md").is_file():
            backup = BACKUP_DIR / f"skill-{folder.lstrip('.')}-{timestamp()}"
            shutil.copytree(target, backup)
            shutil.rmtree(target)
            removed.append(str(target))
    return removed


# ---------------------------------------------------------------------------
# 바로 쓰는 rag(다시 시작하지 않은 VS Code, AI 도구에서도 rag를 찾게 하는 작은 실행 파일)
# ---------------------------------------------------------------------------

SHIM_MARK = "local-rag shim"


def path_entries(value=None):
    value = os.environ.get("PATH", "") if value is None else value
    return [Path(os.path.expandvars(part.strip().strip('"'))) for part in value.split(os.pathsep) if part.strip()]


def same_folder(a, b):
    def norm(path):
        text = os.path.normpath(str(path)).rstrip("\\/")
        return text.lower() if IS_WINDOWS else text
    return norm(a) == norm(b)


def shim_dir():
    """이미 열려 있는 프로그램의 PATH에도 들어 있는 사용자 폴더. 없으면 None."""
    if IS_WINDOWS:
        candidates = [Path(os.environ.get("LOCALAPPDATA", str(home() / "AppData" / "Local"))) / "Microsoft" / "WindowsApps"]
    else:
        candidates = [home() / ".local" / "bin", home() / "bin"]
    entries = path_entries()
    for candidate in candidates:
        if any(same_folder(candidate, entry) for entry in entries) and candidate.is_dir() and os.access(candidate, os.W_OK):
            return candidate
    return None


def shim_file(folder=None):
    folder = folder or shim_dir()
    return None if folder is None else folder / ("rag.cmd" if IS_WINDOWS else "rag")


ALIAS_NAME = "local-rag-kit"


def kit_alias():
    """키트 경로에 한글이 있을 때 쓰는 영문 이름의 디렉터리 연결(%LOCALAPPDATA%\\local-rag-kit)."""
    return Path(os.environ.get("LOCALAPPDATA", str(home() / "AppData" / "Local"))) / ALIAS_NAME


def needs_alias(kit=KIT):
    """배치 파일은 콘솔 코드 페이지로 읽혀서, AI 도구가 콘솔을 UTF-8(65001)로 바꾸면 CP949로 쓴 한글 경로를 찾지 못한다.
    그래서 키트 경로에 영문이 아닌 글자가 있으면 실행 파일에는 영문 이름의 연결만 적는다."""
    return IS_WINDOWS and not str(kit).isascii()


def alias_ok(kit=KIT):
    alias = kit_alias()
    try:
        return is_link(alias) and os.path.samefile(alias, kit)
    except OSError:
        return False


def make_alias(kit=KIT):
    alias = kit_alias()
    if alias_ok(kit):
        return True
    if is_link(alias):
        remove_link(alias)
    elif alias.exists():
        return False
    result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(kit)], capture_output=True)
    return result.returncode == 0 and alias_ok(kit)


def shim_text(kit=KIT):
    if IS_WINDOWS:
        target = f"%LOCALAPPDATA%\\{ALIAS_NAME}\\bin\\rag.cmd" if needs_alias(kit) else str(launcher(kit))
        return (f"@echo off\r\nrem {SHIM_MARK}: runs bin\\rag.cmd of the local-rag kit folder.\r\n"
                f"\"{target}\" %*\r\n")
    return f"#!/bin/sh\n# {SHIM_MARK}: runs bin/rag of the local-rag kit folder.\nexec {shell_quote(str(launcher(kit)))} \"$@\"\n"


def shim_bytes(kit=KIT):
    """배치 파일은 콘솔 코드 페이지로 읽히므로 그 인코딩으로 쓴다. 쓸 수 없는 글자가 있으면 None."""
    text = shim_text(kit)
    if not IS_WINDOWS:
        return text.encode("utf-8")
    if "%" in str(kit):
        return None
    try:
        import ctypes
        code_page = ctypes.windll.kernel32.GetOEMCP()
        return text.encode(f"cp{code_page}")
    except (UnicodeEncodeError, LookupError, OSError, AttributeError):
        return None


def bash_shim_bytes(kit=KIT):
    """Windows의 Git Bash(Claude Code 등이 쓰는 셸)는 rag.cmd를 이름만으로 실행하지 못해 확장자 없는 실행 파일을 함께 둔다."""
    return (f"#!/bin/sh\n# {SHIM_MARK}: runs bin/rag of the local-rag kit folder (Git Bash).\n"
            f"exec {shell_quote(git_bash_path(kit / 'bin' / 'rag'))} \"$@\"\n").encode("utf-8")


def bash_shim_ok(folder, kit=KIT):
    path = folder / "rag"
    return not IS_WINDOWS or (path.exists() and (not is_our_shim(path) or path.read_bytes() == bash_shim_bytes(kit)))


def is_our_shim(path):
    try:
        return path.is_file() and SHIM_MARK.encode() in path.read_bytes()[:400]
    except OSError:
        return False


def shim_state(kit=KIT):
    path = shim_file()
    if path is None:
        return "쓸 폴더 없음", None
    if not path.exists():
        return "없음", path
    if not is_our_shim(path):
        return "다른 파일 있음", path
    current = path.read_bytes() == shim_bytes(kit) and bash_shim_ok(path.parent, kit) and (not needs_alias(kit) or alias_ok(kit))
    return ("최신" if current else "옛 버전"), path


def install_shim(kit=KIT):
    state, path = shim_state(kit)
    if state in ("쓸 폴더 없음", "다른 파일 있음"):
        return None
    if needs_alias(kit) and not make_alias(kit):
        return None  # 연결을 만들지 못하면 실행 파일을 두지 않고, 스킬에 적은 전체 경로로 실행하게 한다.
    if IS_WINDOWS and not needs_alias(kit) and is_link(kit_alias()):
        remove_link(kit_alias())  # 예전 한글 경로 키트에 쓰던 연결은 이제 필요 없다.
    data = shim_bytes(kit)
    if data is None:
        return None
    if state != "최신":
        path.write_bytes(data)
        if not IS_WINDOWS:
            path.chmod(0o755)
        companion = path.parent / "rag"
        if IS_WINDOWS and (not companion.exists() or is_our_shim(companion)):
            companion.write_bytes(bash_shim_bytes(kit))
    return path


def remove_shim():
    removed = []
    folders = [shim_dir()] if shim_dir() else []
    if IS_WINDOWS:
        folders.append(Path(os.environ.get("LOCALAPPDATA", str(home() / "AppData" / "Local"))) / "Microsoft" / "WindowsApps")
    else:
        folders += [home() / ".local" / "bin", home() / "bin"]
    for folder in folders:
        for path in [shim_file(folder)] + ([folder / "rag"] if IS_WINDOWS else []):
            if path and is_our_shim(path) and str(path) not in removed:
                path.unlink()
                removed.append(str(path))
    if IS_WINDOWS and is_link(kit_alias()):
        remove_link(kit_alias())  # 연결만 지우고 키트 폴더의 내용은 그대로 둔다.
        removed.append(str(kit_alias()))
    return removed


# ---------------------------------------------------------------------------
# VS Code 자동 승인 규칙(settings.json은 주석이 있을 수 있어 글자 단위로 고친다)
# ---------------------------------------------------------------------------

def vscode_settings_files():
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", str(home() / "AppData" / "Roaming")))
    elif IS_MAC:
        base = home() / "Library" / "Application Support"
    else:
        base = home() / ".config"
    return [base / name / "User" / "settings.json" for name in ("Code", "Code - Insiders")
            if (base / name / "User").is_dir()]


def skip_space(text, index):
    """공백과 주석을 건너뛴 다음 위치."""
    length = len(text)
    while index < length:
        if text[index] in " \t\r\n":
            index += 1
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end < 0 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end < 0 else end + 2
        else:
            break
    return index


def string_end(text, index):
    """text[index]가 따옴표일 때 문자열이 끝난 다음 위치."""
    index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index + 1
        index += 1
    raise ValueError("문자열이 닫히지 않았습니다.")


def value_end(text, index):
    """index에서 시작하는 JSON 값이 끝난 다음 위치(주석 허용)."""
    if text[index] == '"':
        return string_end(text, index)
    if text[index] in "{[":
        depth = 0
        while index < len(text):
            index = skip_space(text, index)
            if index >= len(text):
                break
            char = text[index]
            if char == '"':
                index = string_end(text, index)
                continue
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        raise ValueError("괄호가 닫히지 않았습니다.")
    match = re.compile(r"[^,\s\]}/]+").match(text, index)
    if not match:
        raise ValueError("값을 읽을 수 없습니다.")
    return match.end()


def jsonc_loads(text):
    """주석과 끝 쉼표가 있는 JSON을 읽는다."""
    output, index = [], 0
    while index < len(text):
        next_index = skip_space(text, index)
        if next_index != index:
            output.append(" ")
            index = next_index
            continue
        char = text[index]
        if char == '"':
            end = string_end(text, index)
            output.append(text[index:end])
            index = end
            continue
        if char == ",":
            after = skip_space(text, index + 1)
            if after < len(text) and text[after] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    joined = "".join(output).strip()
    return json.loads(joined) if joined else {}


def object_members(text, start):
    """text[start]가 '{'인 객체의 (키, 키 시작, 값 시작, 값 끝) 목록."""
    members, index = [], skip_space(text, start + 1)
    while index < len(text) and text[index] != "}":
        key_end = string_end(text, index)
        key = json.loads(text[index:key_end])
        colon = skip_space(text, key_end)
        value_start = skip_space(text, colon + 1)
        end = value_end(text, value_start)
        members.append((key, index, value_start, end))
        index = skip_space(text, end)
        if index < len(text) and text[index] == ",":
            index = skip_space(text, index + 1)
    return members


def insert_members(text, brace, lines, indent):
    """'{' 바로 뒤에 멤버 줄을 넣는다. 객체가 비어 있으면 끝 쉼표를 붙이지 않는다."""
    empty = text[skip_space(text, brace + 1)] == "}"
    closing_indent = indent[:-4] if len(indent) >= 4 else ""
    if empty:
        body = ",\n".join(indent + line for line in lines)
        end = skip_space(text, brace + 1)
        return text[:brace + 1] + "\n" + body + "\n" + closing_indent + text[end:]
    body = "".join(f"\n{indent}{line}," for line in lines)
    return text[:brace + 1] + body + text[brace + 1:]


def settings_with_rules(text, rules=APPROVE_RULES):
    """자동 승인 규칙을 넣은 새 글을 돌려준다. 이미 있는 규칙은 사용자의 값을 그대로 둔다."""
    if not text.strip():
        text = "{}"
    root = skip_space(text, 0)
    if text[root] != "{":
        raise ValueError("settings.json의 맨 바깥이 객체가 아닙니다.")
    members = {key: (key_start, value_start, end) for key, key_start, value_start, end in object_members(text, root)}
    if APPROVE_KEY in members:
        _, value_start, _ = members[APPROVE_KEY]
        if text[value_start] != "{":
            raise ValueError(f"{APPROVE_KEY} 값이 객체가 아닙니다.")
        existing = {key for key, *_ in object_members(text, value_start)}
        lines = [f"{json.dumps(rule)}: {json.dumps(value)}" for rule, value in rules if rule not in existing]
        if not lines:
            return text
        new_text = insert_members(text, value_start, lines, "        ")
    else:
        inner = ",\n".join(f"        {json.dumps(rule)}: {json.dumps(value)}" for rule, value in rules)
        new_text = insert_members(text, root, [f"{json.dumps(APPROVE_KEY)}: {{\n{inner}\n    }}"], "    ")
    parsed = jsonc_loads(new_text)
    if not all(rule in parsed.get(APPROVE_KEY, {}) for rule, _ in rules):
        raise ValueError("규칙을 넣은 결과를 확인하지 못했습니다.")
    return new_text


def vscode_rules_state():
    files = vscode_settings_files()
    if not files:
        return "VS Code 없음", []
    missing = []
    for path in files:
        try:
            data = jsonc_loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            rules = data.get(APPROVE_KEY, {}) if isinstance(data, dict) else {}
            if not all(rule in rules for rule, _ in APPROVE_RULES):
                missing.append(path)
        except (OSError, ValueError):
            missing.append(path)
    return ("있음" if not missing else "없음"), missing


def install_vscode_rules():
    done, manual = [], []
    for path in vscode_settings_files():
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            new_text = settings_with_rules(text)
        except (ValueError, json.JSONDecodeError) as error:
            manual.append(f"{path}: {error}")
            continue
        if new_text != text:
            if path.exists():
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, BACKUP_DIR / f"vscode-settings-{timestamp()}.json")
            path.write_text(new_text, encoding="utf-8")
        done.append(str(path))
    return done, manual


# ---------------------------------------------------------------------------
# 다운로드(반입 준비)
# ---------------------------------------------------------------------------

def download(url, target, label=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    label = label or str(target.relative_to(KIT) if KIT in target.parents else target)
    note(f"받는 중: {label}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as file:
            total = int(response.headers.get("Content-Length") or 0)
            done, shown = 0, -1
            for block in iter(lambda: response.read(1024 * 1024), b""):
                file.write(block)
                done += len(block)
                if total and PROGRESS:
                    PROGRESS.update(done, total, f"{label} {done / 1024 ** 2:,.0f}MB / {total / 1024 ** 2:,.0f}MB")
                elif total:
                    percent = done * 100 // total // 10 * 10
                    if percent != shown:
                        say(f"    {percent}% ({done / 1024 ** 2:,.0f}MB / {total / 1024 ** 2:,.0f}MB)")
                        shown = percent
        if total and partial.stat().st_size != total:
            raise KitError(f"다운로드가 중간에 끊겼습니다: {url}. 다시 요청하면 처음부터 받습니다.")
    except urllib.error.URLError as error:
        partial.unlink(missing_ok=True)
        raise KitError(explain_network_error(error, url)) from error
    os.replace(partial, target)
    return target


def remote_size(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
            return int(response.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def ensure_wheels(targets):
    folder = OFFLINE / "wheels"
    have = [path.name for path in folder.glob("*.whl") if not is_junk(path.name)] if folder.is_dir() else []
    wanted = {"windows": [("windows", "amd64")], "mac": [("mac", "arm64"), ("mac", "x86_64")],
              "linux": [("linux", "x86_64"), ("linux", "aarch64")]}
    missing = [(os_name, machine) for target in targets for os_name, machine in wanted[target]
               if not any(wheel_tag_matches(name, os_name, machine) for name in have)]
    if not missing:
        return have
    with urllib.request.urlopen(f"https://pypi.org/pypi/sqlite-vec/{SQLITE_VEC_VERSION}/json", timeout=30) as response:
        files = json.loads(response.read().decode("utf-8"))["urls"]
    for os_name, machine in missing:
        for item in files:
            if wheel_tag_matches(item["filename"], os_name, machine):
                path = download(item["url"], folder / item["filename"])
                if file_sha256(path) != item["digests"]["sha256"]:
                    path.unlink()
                    raise KitError(f"받은 파일의 해시가 다릅니다: {item['filename']}")
    return [path.name for path in folder.glob("*.whl") if not is_junk(path.name)]


def prepare_targets(text):
    targets = [item.strip() for item in text.split(",") if item.strip()]
    for target in targets:
        if target not in DOWNLOADS:
            raise KitError(f"--os에는 windows, mac, linux만 쓸 수 있습니다: {target}")
    return targets


def prepare_models(text):
    models = [normalize_model(item) for item in (text or "").split(",") if item.strip()] or [default_model()]
    for model in models:
        if not catalog_entry(model):
            say(f"참고: {model}은 models.json 목록에 없는 모델입니다. 질문과 문서 형식 없이 씁니다.")
    return models


def gather_offline(targets, models):
    """반입 재료를 offline 폴더에 모은다. 이 PC에는 아무것도 설치하지 않는다."""
    start(0)
    ensure_wheels(targets)
    finish("sqlite-vec 설치 파일")
    start(1)
    for target in targets:
        for relative, url in DOWNLOADS[target]:
            path = OFFLINE / relative
            size = remote_size(url)
            if path.is_file() and size and path.stat().st_size == size:
                note(f"이미 있음: {relative}")
                continue
            if free_bytes(OFFLINE) < size + 500 * 1024 ** 2:
                raise KitError(f"디스크 여유 공간이 부족합니다({size / 1024 ** 3:.1f}GB 필요).")
            download(url, path)
    finish("Ollama, Python 설치 파일")
    start(2, f"임베딩 모델 {', '.join(models)}")
    source = ollama_models_dir()
    local = ollama_models() if ollama_running() else None
    for model in models:
        if local and model in local and model_files(source, model):
            note(f"이 PC의 Ollama에 있는 {model} 모델 파일을 복사합니다.")
            copy_model(source, OFFLINE / "models", model)
        else:
            note(f"{model} 모델을 모델 저장소에서 직접 받습니다(이 PC에는 설치하지 않음).")
            download_model_from_registry(OFFLINE / "models", model)
    finish()
    files = []
    for path in sorted(OFFLINE.rglob("*")):
        if path.is_file() and not is_junk(path.name) and path.suffix != ".part" and path.name != "MANIFEST.json":
            files.append({"path": path.relative_to(OFFLINE).as_posix(), "size": path.stat().st_size})
    save_json(OFFLINE / "MANIFEST.json", {
        "prepared_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "targets": targets, "models": offline_models(), "default_model": models[0], "sqlite_vec": SQLITE_VEC_VERSION,
        "python_windows": PYTHON_WINDOWS_VERSION, "files": files,
    })
    return sum(item["size"] for item in files)


def command_prepare(args):
    targets, models = prepare_targets(args.os), prepare_models(args.model)
    begin("로컬 RAG 반입 재료 받기", ["sqlite-vec 설치 파일", "Ollama, Python 설치 파일", "임베딩 모델"], args)
    try:
        total = gather_offline(targets, models)
    except BaseException as error:
        end(False, str(error) if isinstance(error, KitError) else "중간에 멈췄습니다.")
        raise
    end(True, f"반입 재료를 모았습니다({total / 1024 ** 3:.2f}GB).")
    say("")
    say(f"반입 재료를 모두 모았습니다: {OFFLINE} (모두 {total / 1024 ** 3:.2f}GB)")
    say("이제 외장 드라이브에 복사하세요. AI에게 'E 드라이브에 반입용으로 복사해 줘'처럼 요청하면 됩니다.")
    return 0


# ---------------------------------------------------------------------------
# 복사
# ---------------------------------------------------------------------------

def copy_tree(source, destination, with_indexes=False, targets=None):
    """키트 폴더를 복사한다. targets(운영체제 목록)를 주면 다른 운영체제의 설치 파일은 빼고 복사한다."""
    copied, total = 0, 0
    skip_os = {name for name in ("windows", "mac", "linux") if targets and name not in targets}
    for directory, dirs, files in os.walk(source):
        relative_dir = Path(directory).relative_to(source)
        dirs[:] = [name for name in dirs if not is_junk(name) and not (relative_dir == Path(".") and name in COPY_SKIP)
                   and not (relative_dir == Path(".") and name == "indexes" and not with_indexes)
                   and not (relative_dir.parts[:1] == ("offline",) and len(relative_dir.parts) == 2 and name in skip_os)
                   and name != "__pycache__"]
        for name in files:
            if is_junk(name) or name.endswith(".part") or (relative_dir == Path(".") and name in COPY_SKIP):
                continue
            if relative_dir == Path("indexes") and name.endswith(("-wal", "-shm")):
                continue
            source_file = Path(directory) / name
            target_file = Path(destination) / relative_dir / name
            target_file.parent.mkdir(parents=True, exist_ok=True)
            stat = source_file.stat()
            size = stat.st_size
            same = False
            if target_file.exists():
                target_stat = target_file.stat()
                # exFAT, FAT는 수정 시각을 2초 단위로 저장하므로 2초까지는 같은 파일로 본다.
                same = target_stat.st_size == size and abs(target_stat.st_mtime - stat.st_mtime) <= 2
            if not same:
                if size > 100 * 1024 ** 2:
                    say(f"  복사 중(큰 파일): {relative_dir / name} ({size / 1024 ** 2:,.0f}MB)")
                shutil.copy2(source_file, target_file)
            copied += 1
            total += size
    return copied, total


def copy_destination(text):
    destination = Path(text).expanduser()
    destination = destination.resolve() if destination.exists() else destination.absolute()
    if destination == KIT or KIT in destination.parents:
        raise KitError("복사할 곳이 지금 폴더이거나 그 안입니다. 다른 위치를 알려 주세요.")
    if destination.exists() and any(destination.iterdir()) and not (destination / "rag.py").exists():
        raise KitError(f"{destination}이 비어 있지 않습니다. 빈 폴더나 새 폴더 이름을 알려 주세요.")
    return destination


def copy_kit(destination, with_indexes, targets=None):
    need = sum(path.stat().st_size for path in KIT.rglob("*") if path.is_file())
    if free_bytes(destination) < need:
        raise KitError(f"복사할 곳의 여유 공간이 부족합니다(최대 {need / 1024 ** 3:.1f}GB 필요).")
    note(f"복사합니다: {KIT} -> {destination}")
    return copy_tree(KIT, destination, with_indexes, targets)


def command_copy_to(args):
    destination = copy_destination(args.destination)
    if args.with_indexes:
        say("색인(indexes)도 함께 복사합니다. 색인에는 문서 내용 조각이 들어 있으니 반출 규정을 확인하세요.")
    copied, total = copy_kit(destination, args.with_indexes)
    say(f"파일 {copied}개({total / 1024 ** 3:.2f}GB)를 복사했습니다. 가상 환경(.venv), PC별 설정(config.json)은 옮기지 않았습니다.")
    say(f"복사한 폴더에서 설치하려면: {command_line(sys.executable, destination / 'setup' / 'kit.py', 'install')}")
    return 0


def carry_guide(destination, targets, total, with_indexes):
    manifest = load_json(OFFLINE / "MANIFEST.json") or {}
    models = manifest.get("models") or []
    lines = [
        "로컬 RAG 반입 안내",
        "",
        f"이 폴더({destination.name})를 통째로 사내 PC에 가져가면 됩니다. 다른 파일은 챙기지 않아도 됩니다.",
        f"준비한 날: {manifest.get('prepared_at', '')}",
        f"크기: {total / 1024 ** 3:.2f}GB",
        f"사내 PC 운영체제: {', '.join(targets)}",
        f"임베딩 모델: {', '.join(models)} (기본: {manifest.get('default_model', '')})",
        f"색인: {'함께 넣음(문서 내용 조각이 들어 있으니 반출 규정을 확인하세요)' if with_indexes else '넣지 않음(사내 PC에서 사내 문서로 새로 만듭니다)'}",
        "",
        "사내 PC에서 할 일",
        f"1. 외장 드라이브의 {destination.name} 폴더를 AI 도구(VS Code의 Copilot, Claude Code 등)에서 엽니다.",
        "2. AI에게 '설치해 줘'라고 요청합니다. 홈 폴더로 복사하는 것부터 인터넷 없이 설치하는 것까지 AI가 처리합니다.",
        "3. 설치가 끝나면 아무 프로젝트에서 '/local-rag 목록 보여 줘'로 확인합니다.",
        "",
        "들어 있는 것",
        "- rag.py, setup, skill, bin: 로컬 RAG 도구와 설치 도우미",
        "- offline/wheels: sqlite-vec 설치 파일",
        "- offline/ollama: Ollama 설치 파일",
        "- offline/python: Windows용 Python 설치 파일(사내 PC에 Python이 없을 때만 씀)",
        "- offline/models: 임베딩 모델 파일",
        "",
        "사내망에서도 AI 도구는 그 서비스(GitHub Copilot 등)에 접속할 수 있어야 합니다. 색인과 임베딩은 PC 안에서만 동작합니다.",
    ]
    path = destination / "반입 안내.txt"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
    return path


def command_pack(args):
    """반입 준비를 한 번에: 재료 받기, 외장 드라이브로 복사, 확인, 안내 파일."""
    targets, models = prepare_targets(args.os), prepare_models(args.model)
    destination = copy_destination(args.destination)
    begin("로컬 RAG 반입 준비", ["sqlite-vec 설치 파일", "Ollama, Python 설치 파일", "임베딩 모델", "외장 드라이브로 복사",
                               "복사한 파일 확인"], args)
    try:
        return pack_steps(args, targets, models, destination)
    except BaseException as error:
        end(False, str(error) if isinstance(error, KitError) else "중간에 멈췄습니다.")
        raise


def pack_steps(args, targets, models, destination):
    gather_offline(targets, models)
    start(3)
    copied, total = copy_kit(destination, args.with_indexes, targets)
    finish(f"파일 {copied}개, {total / 1024 ** 3:.2f}GB")
    start(4)
    problems = []
    skip_os = {name for name in ("windows", "mac", "linux") if name not in targets}
    for path in sorted(OFFLINE.rglob("*")):
        relative = path.relative_to(OFFLINE)
        if len(relative.parts) > 2 and relative.parts[1] in skip_os and relative.parts[0] in ("ollama", "python"):
            continue
        if path.is_file() and not is_junk(path.name) and path.suffix != ".part":
            target = destination / "offline" / relative
            if not target.is_file() or target.stat().st_size != path.stat().st_size:
                problems.append(str(path.relative_to(OFFLINE)))
    for model in models:
        if not model_files(destination / "offline" / "models", model):
            problems.append(f"모델 {model}")
    if problems:
        end(False, "복사한 파일 중 다른 것이 있습니다.")
        raise KitError("복사한 파일 중 원본과 다른 것이 있습니다: " + ", ".join(problems[:5]) + ". 다시 요청하세요.")
    guide = carry_guide(destination, targets, total, args.with_indexes)
    finish("크기와 모델 파일 확인")
    end(True, f"{destination}에 반입 준비를 마쳤습니다({total / 1024 ** 3:.2f}GB).")
    say("")
    say(f"반입 준비를 마쳤습니다: {destination} (파일 {copied}개, {total / 1024 ** 3:.2f}GB)")
    say(f"- 이 폴더 하나만 가져가면 됩니다. 안내 파일: {guide}")
    say("- 사내 PC에서는 이 폴더를 AI 도구에서 열고 '설치해 줘'라고 요청하면 됩니다.")
    return 0


# ---------------------------------------------------------------------------
# 점검
# ---------------------------------------------------------------------------

def collection_sources():
    rows = []
    if not INDEX_DIR.is_dir():
        return rows
    for path in sorted(INDEX_DIR.glob("*.db")):
        if path.name.startswith("."):
            continue
        try:
            connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
            try:
                metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            finally:
                connection.close()
            rows.append((path.stem, metadata.get("source", ""), Path(metadata.get("source", "")).is_dir()))
        except sqlite3.Error:
            rows.append((path.stem, "(읽을 수 없음)", False))
    return rows


# ---------------------------------------------------------------------------
# 진행 상황
# ---------------------------------------------------------------------------

def begin(title, steps, args):
    global PROGRESS
    from progress import Progress
    PROGRESS = Progress(title, steps, PROGRESS_PAGE, open_browser=not getattr(args, "no_browser", False))
    say(f"진행 상황 화면: {PROGRESS_PAGE}")


def start(index, label=None):
    if PROGRESS:
        PROGRESS.start(index, label)


def finish(text=""):
    if PROGRESS:
        PROGRESS.finish_step(text)


def end(ok, message=""):
    if PROGRESS:
        PROGRESS.close(ok, message)


# ---------------------------------------------------------------------------
# Claude Code 자동 승인 규칙(~/.claude/settings.json, 주석 없는 JSON)
# ---------------------------------------------------------------------------

def claude_settings_file():
    return home() / ".claude" / "settings.json"


def claude_installed():
    """Claude Code를 쓰는 PC인지. ~/.claude 폴더는 스킬을 넣을 때 키트가 만들 수도 있어 그것만으로는 판단하지 않는다."""
    return ((home() / ".claude.json").exists() or claude_settings_file().exists()
            or bool(shutil.which("claude")) or (home() / ".claude" / "projects").is_dir())


def claude_rules_state():
    path = claude_settings_file()
    if not claude_installed():
        return "Claude Code 없음"
    data = load_json(path, {}) if path.exists() else {}
    if not isinstance(data, dict):
        return "읽을 수 없음"
    allowed = (data.get("permissions") or {}).get("allow") or []
    return "있음" if all(rule in allowed for rule in CLAUDE_RULES) else "없음"


def install_claude_rules(installed=None):
    path = claude_settings_file()
    if not (claude_installed() if installed is None else installed):
        return None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError) as error:
            raise KitError(f"{path}를 읽을 수 없어 Claude Code 규칙을 넣지 못했습니다({error}).") from error
    else:
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("permissions", {}), dict):
        raise KitError(f"{path}의 모양이 예상과 달라 Claude Code 규칙을 넣지 못했습니다.")
    permissions = data.get("permissions")
    if permissions is None:
        permissions = data["permissions"] = {}
    allowed = permissions.get("allow")
    if allowed is None:
        allowed = permissions["allow"] = []
    if not isinstance(allowed, list):
        raise KitError(f"{path}의 permissions.allow가 목록이 아니라 Claude Code 규칙을 넣지 못했습니다.")
    missing = [rule for rule in CLAUDE_RULES if rule not in allowed]
    if missing:
        if path.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, BACKUP_DIR / f"claude-settings-{timestamp()}.json")
        allowed.extend(missing)
        save_json(path.resolve(), data)  # 설정 파일이 링크(dotfiles 등)여도 링크는 그대로 두고 실제 파일을 고친다.
    return path


# ---------------------------------------------------------------------------
# 이전 키트 폴더(새 버전을 다른 폴더에 받아 다시 설치할 때 색인을 가져온다)
# ---------------------------------------------------------------------------

def previous_kits():
    found = []
    if IS_WINDOWS:
        value = windows_registry_value("RAG_HOME")
        if value:
            found.append(value)
    else:
        try:
            text = shell_rc_file().read_text(encoding="utf-8")
            match = re.search(r"^export RAG_HOME='((?:[^']|'\"'\"')*)'$", text, re.M)
            if match:
                found.append(match.group(1).replace("'\"'\"'", "'"))
        except OSError:
            pass
    found += installed_kit_paths()
    kits = []
    for value in found:
        path = Path(value)
        if not same_folder(path, KIT) and (path / "rag.py").is_file() and not any(same_folder(path, item) for item in kits):
            kits.append(path)
    return kits


def importable_indexes(kits=None):
    """이전 키트 폴더에만 있는 색인 파일."""
    have = {path.name for path in INDEX_DIR.glob("*.db")} if INDEX_DIR.is_dir() else set()
    found = []
    for kit in previous_kits() if kits is None else kits:
        for path in sorted((kit / "indexes").glob("*.db")) if (kit / "indexes").is_dir() else []:
            if not path.name.startswith(".") and path.name not in have:
                found.append(path)
                have.add(path.name)
    return found


def import_indexes(kits=None):
    copied = []
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    for path in importable_indexes(kits):
        target = INDEX_DIR / path.name
        source = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(str(target))
            try:
                source.backup(destination)  # 쓰는 중인 WAL 내용까지 안전하게 복사
            finally:
                destination.close()
        finally:
            source.close()
        copied.append(f"{path.stem}(원래 {path.parent.parent})")
    return copied


# ---------------------------------------------------------------------------
# 점검
# ---------------------------------------------------------------------------

def check_items():
    items = []

    def add(name, ok, detail, fix=""):
        items.append((name, ok, detail, fix))

    problems = location_problems()
    add("키트 위치", None if problems else True, f"{KIT}" + (f" ({' '.join(problems)})" if problems else ""),
        f"홈 폴더로 복사해서 쓰세요. AI에게 '홈 폴더로 복사해서 설치해 줘'라고 요청하면 됩니다({suggested_home_folder()})."
        if problems else "")
    version = venv_state()
    problem = None if version else python_problem()
    add("Python", problem is None, f"{sys.version.split()[0]} ({sys.executable})" + (f": {problem}" if problem else ""),
        "AGENTS.md의 'Python 찾기' 순서로 알맞은 Python을 찾아 다시 실행하세요." if problem else "")
    add("sqlite-vec(.venv)", bool(version), f"sqlite-vec {version}" if version else "가상 환경이 없거나 이 PC에서 동작하지 않음",
        "키트 폴더를 연 채로 '설치해 줘'라고 요청하세요." if not version else "")
    config = load_json(CONFIG_FILE)
    add("config.json", bool(config), f"있음, 기본 모델 {config.get('embed_model')}" if config else "없음",
        "" if config else "'설치해 줘'로 만듭니다.")
    running = ollama_running()
    add("Ollama", bool(running), f"{ollama_url()} 응답, 버전 {running}" if running else f"{ollama_url()} 응답 없음",
        "" if running else ("Ollama 앱을 실행하세요(Windows는 시작 메뉴, macOS는 응용 프로그램)." if find_ollama_app()
                            else "'설치해 줘'로 Ollama를 설치합니다."))
    models = ollama_models() if running else None
    wanted = [default_model()] + [model for model in collection_models() if model != default_model()]
    for model in wanted:
        has_model = bool(models and model in models)
        users = collection_models().get(model, [])
        add(f"임베딩 모델 {model}", has_model if running else None,
            ("있음" if has_model else "없음" if running else "(Ollama 확인 뒤)") + (" (기본)" if model == default_model() else "")
            + (f", 쓰는 컬렉션 {len(users)}개" if users else ""),
            "" if has_model else f"AI에게 '{model} 모델을 받아 줘'라고 요청하세요(`rag models --add {model}`).")
    configured = path_configured()
    shim, shim_path = shim_state()
    on_path = shutil.which("rag")
    detail = "설정됨" if configured else "설정 안 됨"
    if shim == "최신":
        detail += f", 바로 쓰는 실행 파일 {shim_path}"
    elif configured and not on_path:
        detail += ", 지금 창에는 아직 반영 안 됨(AI 도구나 VS Code를 완전히 종료했다가 다시 열면 반영)"
    add("rag 명령(PATH)", configured, detail, "" if configured else "'설치해 줘'로 등록합니다.")
    for (folder, label), target in zip(SKILL_HOMES, skill_targets()):
        state = target_state(target)
        add(f"local-rag 스킬({label})", state == "최신", f"{target} ({state})",
            "" if state == "최신" else "'설치해 줘'로 설치하거나 최신으로 바꿉니다.")
    rules, _ = vscode_rules_state()
    add("VS Code 자동 승인 규칙", True if rules != "없음" else None, rules,
        "" if rules != "없음" else "'설치해 줘'로 넣거나, 넣지 않으면 rag 명령마다 승인을 누르면 됩니다.")
    claude = claude_rules_state()
    add("Claude Code 자동 승인 규칙", True if claude != "없음" else None, claude,
        "" if claude != "없음" else "'설치해 줘'로 넣거나, 넣지 않으면 rag 명령마다 승인을 누르면 됩니다.")
    for name, source, exists in collection_sources():
        add(f"컬렉션 {name}", exists or None, source + ("" if exists else " (원본 폴더 없음)"),
            "" if exists else f"폴더를 옮겼다면 '/local-rag {name} 컬렉션의 원본 폴더를 <새 경로>로 옮겼어'라고 요청하세요.")
    return items


def command_check(_args=None):
    say(f"local-rag 점검 ({current_os()}, {platform.machine()}, Python {python_machine()})")
    failed = False
    for name, ok, detail, fix in check_items():
        label = "통과" if ok is True else "확인 필요" if ok is None else "실패"
        failed = failed or ok is False
        say(f"[{label}] {name}: {detail}")
        if fix:
            say(f"        다음에 할 일: {fix}")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# 설치
# ---------------------------------------------------------------------------

def install_plan(model=None):
    """설치하면 무엇을 하는지(특히 PC 설정을 바꾸는 것) 미리 정리한다."""
    steps = []
    version = venv_state()
    steps.append(("가상 환경과 sqlite-vec", "그대로 둠" if version else
                  ("반입 파일로 설치" if offline_wheel() else "인터넷에서 받아 설치"), False))
    if ollama_running():
        steps.append(("Ollama", "실행 중, 그대로 둠", False))
    elif find_ollama_app():
        steps.append(("Ollama", "설치되어 있음, 앱 실행", False))
    else:
        installer = offline_file("ollama/windows/OllamaSetup.exe" if IS_WINDOWS else "ollama/mac/Ollama-darwin.zip")
        steps.append(("Ollama", "반입한 설치 파일로 설치(관리자 권한 없음, 약 1.8GB)" if installer
                      else "인터넷에서 받아 설치(관리자 권한 없음, Windows는 약 1.8GB)", True))
    present = ollama_models() or []
    parts = []
    for name in needed_models(model):
        if name in present:
            parts.append(f"{model_label(name)} 이미 있음")
        else:
            parts.append(f"{model_label(name)} {'반입 파일에서 복사' if model_files(OFFLINE / 'models', name) else '인터넷에서 받음'}")
    missing = any(name not in present for name in needed_models(model))
    steps.append(("임베딩 모델", "기본 " + "; ".join(parts) + (f" -> {ollama_models_dir()}" if missing else ""), missing))
    steps.append(("config.json", "이 PC의 임베딩 속도를 재서 저장", False))
    target = "사용자 환경 변수 Path와 RAG_HOME" if IS_WINDOWS else str(shell_rc_file())
    shim, shim_path = shim_state()
    shim_text_ = f", 다시 시작하지 않아도 되게 {shim_path} 추가" if shim in ("없음", "옛 버전") else ""
    steps.append(("rag 명령 등록", ("이미 됨" if path_configured() else f"{target}에 {KIT / 'bin'} 추가") + shim_text_,
                  not path_configured() or bool(shim_text_)))
    canonical = skill_targets()[0]
    pending = [f"{target}({label})" for (folder, label), target in zip(SKILL_HOMES, skill_targets())
               if not same_skill_folder(target)
               and (target_state(target) != "최신" or (links_skills() and target != canonical and not target.is_symlink()))]
    steps.append(("AI 도구 스킬", "모두 최신, 그대로 둠" if not pending else f"{', '.join(pending)}에 설치(기존 것은 백업)", bool(pending)))
    rules, missing = vscode_rules_state()
    approve = []
    if rules not in ("VS Code 없음", "있음"):
        approve.append(f"VS Code {', '.join(str(path) for path in missing)}")
    if claude_rules_state() == "없음":
        approve.append(f"Claude Code {claude_settings_file()}")
    steps.append(("자동 승인 규칙", "이미 있음 또는 해당 없음" if not approve else
                  f"{'; '.join(approve)}에 규칙 추가(검색, 목록, 미리보기, 모델 목록만 자동 승인)", bool(approve)))
    imports = importable_indexes()
    steps.append(("이전 키트 폴더의 색인", "없음" if not imports else
                  f"{len(imports)}개 가져오기({', '.join(path.stem for path in imports)})", False))
    steps.append(("자체 시험", "임시 폴더에서 만들기, 검색, 갱신, 옮기기를 시험하고 지움", False))
    return steps


def command_install(args):
    problems = location_problems()
    if problems and not args.here:
        say("설치를 멈췄습니다. " + " ".join(problems))
        say("이 폴더를 홈 폴더로 복사한 뒤 그곳에서 설치하세요. 복사: "
            + command_line(sys.executable, Path(__file__), "copy-to", suggested_home_folder()))
        say("그래도 이 위치에 설치하려면 install에 --here를 붙이세요(드라이브 문자가 바뀌면 다시 설치해야 합니다).")
        return 2
    problem = python_problem()
    if problem:
        raise KitError(problem)
    model = normalize_model(args.model) or None
    if model and not catalog_entry(model):
        say(f"참고: {model}은 models.json 목록에 없는 모델입니다. 질문과 문서 형식 없이 씁니다.")
    if not args.yes:
        say("설치 계획(아직 아무것도 바꾸지 않았습니다)")
        for number, (name, action, changes_pc) in enumerate(install_plan(model), 1):
            say(f"{number}. {name}: {action}" + (" [PC 설정 변경]" if changes_pc else ""))
        say("")
        say(f"기본 임베딩 모델: {model_label(model or default_model())}. 다른 모델 후보는 `{command_line(sys.executable, Path(__file__), 'models')}`로 볼 수 있고, "
            "고르면 install에 --model <모델>을 붙입니다.")
        say("진행하려면 같은 명령에 --yes를 붙여 실행하세요. 자동 승인 규칙을 넣지 않으려면 --no-auto-approve를 함께 붙이세요.")
        return 0
    begin("로컬 RAG 설치", INSTALL_STEPS, args)
    try:
        install_steps(args, model)
    except BaseException as error:
        end(False, str(error) if isinstance(error, KitError) else "중간에 멈췄습니다.")
        raise
    return 0


def install_steps(args, model):
    previous = previous_kits()  # PATH와 스킬을 새 폴더로 바꾸기 전에 예전 키트 폴더를 기억해 둔다.
    claude = claude_installed()  # 스킬 단계가 ~/.claude를 만들기 전에 판단한다(계획과 같게).
    start(0)
    version = venv_state() or make_venv()
    finish(f"sqlite-vec {version}")
    start(1)
    if not ollama_running():
        app = find_ollama_app()
        if app:
            note("Ollama 앱을 실행합니다.")
            if not bring_up_ollama(app, 60):
                raise KitError("Ollama 앱이 응답하지 않습니다. 앱을 직접 실행한 뒤 다시 요청하세요.")
        else:
            install_ollama()
    finish(f"버전 {ollama_running()}")
    start(2)
    for name in needed_models(model):
        note(f"{model_label(name)}: {ensure_model(name)}")
    finish(", ".join(needed_models(model)))
    start(3)
    chosen, results = write_config(model or default_model())
    speed, dimension = results[chosen]
    finish(f"기본 모델 {chosen}, 초당 {speed}개 조각, 벡터 {dimension}차원")
    note(f"기본 모델 {chosen}: 초당 {speed}개 조각, 벡터 {dimension}차원")
    start(4)
    note(configure_path())
    shim = install_shim()
    if shim:
        note(f"다시 시작하지 않아도 바로 쓰도록 추가: {shim}")
    finish()
    start(5)
    for line in install_skill():
        note(line)
    finish()
    start(6)
    if args.no_auto_approve:
        note("건너뜀(--no-auto-approve)")
    else:
        done, manual = install_vscode_rules()
        for path in done:
            note(f"VS Code: {path}")
        for item in manual:
            note(f"VS Code에 직접 넣어야 함: {item}")
        if manual:
            say("  AI에게 VS Code 사용자 설정에 아래 규칙을 넣어 달라고 요청하세요:")
            for rule, value in APPROVE_RULES:
                say(f"    {json.dumps(rule)}: {json.dumps(value)}")
        try:
            claude_path = install_claude_rules(claude)
            if claude_path:
                note(f"Claude Code: {claude_path}")
        except KitError as error:
            note(str(error))
    finish()
    start(7)
    copied = import_indexes(previous)
    for line in copied:
        note(f"가져옴: {line}")
    finish(f"{len(copied)}개" if copied else "가져올 색인 없음")
    start(8)
    note("자체 시험 중입니다(1분 안팎).")
    result = subprocess.run([str(venv_python()), str(KIT / "tests" / "selftest.py")])
    if result.returncode != 0:
        raise KitError("설치한 항목은 그대로 두었지만 자체 시험 중 실패한 항목이 있습니다. 위의 [실패] 줄을 그대로 알려 주세요.")
    finish("모두 통과")
    end(True, "설치를 마쳤습니다.")
    say("")
    say("설치를 마쳤습니다.")
    say(f"- 이 PC의 rag 실행 파일: {launcher()}")
    if shim:
        say(f"- 지금 열려 있는 AI 도구에서도 rag 명령을 바로 쓸 수 있습니다({shim}).")
    else:
        say("- 지금 열려 있는 AI 도구와 터미널은 rag 명령을 못 찾을 수 있습니다. 그동안은 위의 전체 경로로 실행하고, "
            "AI 도구(VS Code 등)를 완전히 종료했다가 다시 열면 rag 이름으로 됩니다.")
    say("- 스킬이 목록에 보이지 않으면 새 대화를 열고, 그래도 없으면 AI 도구를 다시 시작하세요.")
    say("- 아무 프로젝트에서나 '/local-rag 목록 보여 줘'로 확인하세요.")


def command_add_model(args):
    """모델 하나를 더 받는다(반입 파일이 있으면 그것을 쓴다). --default면 새 컬렉션의 기본 모델로 바꾼다."""
    model = normalize_model(args.model)
    if not ollama_running():
        app = find_ollama_app()
        if not app:
            raise KitError("Ollama가 없습니다. 키트 폴더에서 '설치해 줘'로 먼저 설치하세요.")
        if not bring_up_ollama(app, 60):
            raise KitError("Ollama 앱이 응답하지 않습니다. 앱을 직접 실행한 뒤 다시 요청하세요.")
    if not catalog_entry(model):
        say(f"참고: {model}은 models.json 목록에 없는 모델입니다. 질문과 문서 형식 없이 씁니다.")
    say(f"{model_label(model)}: {ensure_model(model)}")
    config = load_json(CONFIG_FILE)
    if not config:
        raise KitError("config.json이 없습니다. 키트 폴더에서 '설치해 줘'로 먼저 설치하세요.")
    chosen, results = write_config(model if args.default else config.get("embed_model"), measure=[model])
    speed, dimension = results[model]
    say(f"속도: 초당 {speed}개 조각, 벡터 {dimension}차원")
    if args.default:
        say(f"기본 모델을 {model}(으)로 바꿨습니다. 새로 만드는 컬렉션부터 이 모델을 씁니다. 기존 컬렉션은 원래 모델 그대로입니다.")
    else:
        say(f"새 컬렉션을 이 모델로 만들려면 `rag index <폴더> --model {model}`, 기존 컬렉션을 바꾸려면 "
            f"`rag index --name <컬렉션> --model {model}`을 실행하세요.")
    return 0


def command_models(_args):
    entries, fallback = model_catalog()
    present = ollama_models()
    used = collection_models()
    say(f"기본 모델: {default_model()}")
    for item in entries:
        state = "확인 못 함" if present is None else "받음" if item["name"] in present else "안 받음"
        users = f", 쓰는 컬렉션 {len(used.get(item['name'], []))}개" if used.get(item["name"]) else ""
        say(f"- {item['name']}: {item['label']}, {item['maker']}({item['country']}), {item['license']}, 약 {item['size_mb']}MB, "
            f"{state}{users}. {item['note']}")
    return 0


def command_uninstall(args):
    if not args.yes:
        say("지울 것: rag 명령 등록(PATH, RAG_HOME, 바로 쓰는 실행 파일), AI 도구 스킬(~/.agents, ~/.claude, ~/.copilot). "
            "Ollama, 모델, 이 폴더의 색인, 자동 승인 규칙은 그대로 둡니다.")
        say("지우려면 --yes를 붙이세요.")
        return 0
    say(f"rag 명령 등록 해제: {configure_path(remove_only=True)}")
    for path in remove_shim():
        say(f"바로 쓰는 실행 파일을 지웠습니다: {path}")
    for path in remove_skills():
        say(f"local-rag 스킬을 지웠습니다: {path}(백업: {BACKUP_DIR})")
    say("자동 승인 규칙은 그대로 두었습니다. rag 명령이 없으면 아무 일도 하지 않습니다.")
    return 0


def main(argv=None):
    setup_output()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    parser = argparse.ArgumentParser(prog="kit.py", description="local-rag 설치 도우미")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("models")
    install = commands.add_parser("install")
    install.add_argument("--yes", action="store_true")
    install.add_argument("--here", action="store_true", help="외장 드라이브 등 지금 위치에 그대로 설치")
    install.add_argument("--no-auto-approve", "--no-vscode", dest="no_auto_approve", action="store_true")
    install.add_argument("--model", help="기본 임베딩 모델(models.json의 이름)")
    install.add_argument("--no-browser", action="store_true", help="진행 상황 화면을 브라우저로 열지 않음")
    add_model = commands.add_parser("add-model")
    add_model.add_argument("model")
    add_model.add_argument("--default", action="store_true")
    default_os = "windows," + current_os() if current_os() != "windows" else "windows"
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--os", default=default_os)
    prepare.add_argument("--model", help="반입할 모델(쉼표로 여러 개, 첫 번째가 기본)")
    prepare.add_argument("--no-browser", action="store_true")
    pack = commands.add_parser("pack", help="반입 준비를 한 번에: 재료 받기, 외장 드라이브로 복사, 확인, 안내 파일")
    pack.add_argument("destination")
    pack.add_argument("--os", default="windows")
    pack.add_argument("--model")
    pack.add_argument("--with-indexes", action="store_true")
    pack.add_argument("--no-browser", action="store_true")
    copy = commands.add_parser("copy-to")
    copy.add_argument("destination")
    copy.add_argument("--with-indexes", action="store_true")
    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    handlers = {"check": command_check, "install": command_install, "prepare": command_prepare, "pack": command_pack,
                "copy-to": command_copy_to, "uninstall": command_uninstall, "add-model": command_add_model,
                "models": command_models}
    try:
        return handlers[args.command](args)
    except KitError as error:
        say(f"오류: {error}")
        return 1
    except subprocess.CalledProcessError as error:
        say(f"오류: 명령이 실패했습니다({error.cmd[0] if error.cmd else ''}, 종료 코드 {error.returncode}).")
        return 1
    except KeyboardInterrupt:
        say("중단했습니다. 같은 요청을 다시 하면 이어서 진행합니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
