#!/usr/bin/env python3
"""local-rag 설치 도우미.

표준 라이브러리만 쓰므로 이 PC의 어떤 Python으로도 실행할 수 있다.
사람이 직접 실행하지 않고, Copilot이 AGENTS.md의 절차에 따라 실행한다.

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
EMBED_MODEL = "qwen3-embedding:0.6b"
MODEL_MANIFEST = ("manifests", "registry.ollama.ai", "library", "qwen3-embedding", "0.6b")
MODEL_REGISTRY = "https://registry.ollama.ai/v2/library/qwen3-embedding"
MODEL_TAG = "0.6b"
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
    ("/^rag remove( |$)/", False),
]
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
COPY_SKIP = {".venv", "__pycache__", ".git", "backup", "config.json"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
TOTAL_STEPS = 8


class KitError(Exception):
    pass


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def say(text=""):
    print(text, flush=True)


def command_line(*parts):
    """터미널에 그대로 붙여 넣을 수 있는 명령. Windows PowerShell은 따옴표로 시작하는 명령 앞에 &가 필요하다."""
    text = " ".join(f'"{part}"' if (" " in str(part) or not str(part).isascii() or "\\" in str(part) or "/" in str(part))
                    else str(part) for part in parts)
    return ("& " + text) if IS_WINDOWS else text


def current_os():
    return "windows" if IS_WINDOWS else "mac" if IS_MAC else "linux"


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
    if executable is None and version < (3, 10):
        return f"이 Python({version.major}.{version.minor})은 너무 오래된 버전입니다. 3.10 이상이 필요합니다."
    connection = sqlite3.connect(":memory:")
    try:
        if not hasattr(connection, "enable_load_extension"):
            if IS_MAC:
                return ("이 Python은 SQLite 확장 불러오기를 지원하지 않습니다(macOS 기본 Python). "
                        "Homebrew나 python.org의 Python으로 다시 실행하세요.")
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
        if not is_junk(path.name) and wheel_tag_matches(path.name, current_os(), platform.machine()):
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
            raise KitError(f"기존 가상 환경을 지우지 못했습니다({error}). VS Code를 완전히 종료했다가 다시 열고 다시 요청하세요.") from error
    subprocess.run([base_python(), "-m", "venv", str(target)], check=True)
    python = str(venv_python())
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    wheel = offline_wheel()
    if wheel:
        say(f"  sqlite-vec를 반입 파일로 설치합니다: {wheel.name}")
        subprocess.run([python, "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True, env=env)
    else:
        if platform.machine().lower() == "arm64" and IS_WINDOWS:
            raise KitError("sqlite-vec는 Windows ARM용이 없습니다. Windows x64 PC에서 사용하세요.")
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
        target = home() / "Applications"
        target.mkdir(exist_ok=True)
        say(f"  Ollama 앱을 {target}에 풉니다(관리자 권한 없이).")
        subprocess.run(["ditto", "-x", "-k", str(installer), str(target)], check=True)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target / "Ollama.app")], check=False)
    app = find_ollama_app()
    if app is None:
        raise KitError("Ollama를 설치했지만 앱을 찾지 못했습니다. 직접 설치 파일을 실행한 뒤 다시 요청하세요.")
    if not wait_for(ollama_running, 20):
        start_ollama_app(app)
    if not wait_for(ollama_running, 90):
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


def model_files(models_dir):
    """모델 폴더에서 이 모델의 manifest와 blob 파일 목록을 돌려준다."""
    manifest = Path(models_dir).joinpath(*MODEL_MANIFEST)
    data = load_json(manifest)
    if not data:
        return None
    digests = [data["config"]["digest"]] + [layer["digest"] for layer in data.get("layers", [])]
    blobs = [Path(models_dir) / "blobs" / digest.replace(":", "-") for digest in digests]
    return manifest, blobs


def copy_model(source_dir, target_dir, verify=True):
    """manifest와 blob을 복사한다. blob 이름이 곧 sha256이므로 복사한 뒤 내용을 검사한다."""
    found = model_files(source_dir)
    if not found:
        raise KitError(f"{source_dir}에 {EMBED_MODEL} 모델 파일이 없습니다.")
    manifest, blobs = found
    need = sum(blob.stat().st_size for blob in blobs)
    if free_bytes(target_dir) < need + 200 * 1024 ** 2:
        raise KitError(f"모델을 복사할 공간이 부족합니다(약 {need / 1024 ** 3:.1f}GB 필요): {target_dir}")
    (Path(target_dir) / "blobs").mkdir(parents=True, exist_ok=True)
    for blob in blobs:
        target = Path(target_dir) / "blobs" / blob.name
        if not (target.exists() and target.stat().st_size == blob.stat().st_size):
            shutil.copyfile(blob, target)
        if verify and file_sha256(target) != blob.name.split("-", 1)[1]:
            target.unlink(missing_ok=True)
            raise KitError(f"모델 파일이 손상됐습니다: {blob.name}. 반입 재료를 다시 복사하세요.")
    target_manifest = Path(target_dir).joinpath(*MODEL_MANIFEST)
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest, target_manifest)


def download_model_from_registry(target_dir):
    """Ollama 없이 모델 저장소(registry.ollama.ai)에서 manifest와 blob을 직접 받는다. 받은 뒤 내용을 검사한다."""
    target_dir = Path(target_dir)
    accept = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
    url = f"{MODEL_REGISTRY}/manifests/{MODEL_TAG}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=accept), timeout=60) as response:
            manifest_bytes = response.read()
    except urllib.error.URLError as error:
        raise KitError(explain_network_error(error, url)) from error
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    digests = [manifest["config"]["digest"]] + [layer["digest"] for layer in manifest.get("layers", [])]
    for digest in digests:
        blob = target_dir / "blobs" / digest.replace(":", "-")
        if blob.is_file() and file_sha256(blob) == digest.split(":", 1)[1]:
            say(f"  이미 있음: {blob.name[:20]}...")
            continue
        download(f"{MODEL_REGISTRY}/blobs/{digest}", blob)
        if file_sha256(blob) != digest.split(":", 1)[1]:
            blob.unlink(missing_ok=True)
            raise KitError(f"받은 모델 파일의 해시가 다릅니다: {digest}. 다시 요청하세요.")
    manifest_path = target_dir.joinpath(*MODEL_MANIFEST)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)


def pull_model():
    say(f"  인터넷에서 {EMBED_MODEL} 모델을 받습니다(약 640MB).")
    last = -1
    try:
        with local_request("/api/pull", {"model": EMBED_MODEL, "stream": True}, timeout=3600) as response:
            for line in response:
                item = json.loads(line.decode("utf-8") or "{}")
                if item.get("error"):
                    raise KitError(f"모델을 받지 못했습니다: {item['error']}")
                total, done = item.get("total"), item.get("completed")
                if total and done:
                    percent = int(done * 100 / total) // 10 * 10
                    if percent != last:
                        say(f"  {percent}%")
                        last = percent
    except (urllib.error.URLError, OSError) as error:
        raise KitError(f"모델을 받지 못했습니다: {error}") from error


def ensure_model():
    if EMBED_MODEL in (ollama_models() or []):
        return "이미 있음"
    offline_models = OFFLINE / "models"
    if model_files(offline_models):
        target = ollama_models_dir()
        say(f"  반입한 모델 파일을 Ollama 모델 폴더로 복사합니다: {target}")
        copy_model(offline_models, target)
        if wait_for(lambda: EMBED_MODEL in (ollama_models() or []), 30):
            return "반입 파일에서 복사"
        raise KitError("모델 파일을 복사했지만 Ollama가 모델을 찾지 못했습니다. Ollama 앱을 종료했다가 다시 실행한 뒤 다시 요청하세요.")
    pull_model()
    if EMBED_MODEL not in (ollama_models() or []):
        raise KitError("모델을 받지 못했습니다. 회사 망이면 인터넷이 되는 PC에서 '반입 준비해 줘'로 받은 폴더를 가져오세요.")
    return "인터넷에서 받음"


def measure_speed(config):
    """한글 문단 16개를 한 번에 임베딩해서 이 PC의 초당 조각 수를 잰다."""
    paragraph = ("사내 문서 검색 속도를 재기 위한 시험 문단입니다. 장비 점검 기준과 보고 절차, 담당자 배정 규칙을 설명합니다. " * 12)[:900]
    payload = {"model": config["embed_model"], "keep_alive": config["keep_alive"], "options": {"num_ctx": config["num_ctx"]}}
    with local_request("/api/embed", dict(payload, input=["준비"]), timeout=300) as response:
        dimension = len(json.loads(response.read().decode("utf-8"))["embeddings"][0])
    started = time.time()
    with local_request("/api/embed", dict(payload, input=[paragraph] * 16), timeout=600) as response:
        json.loads(response.read().decode("utf-8"))
    return round(16 / max(time.time() - started, 0.001), 3), dimension


def write_config():
    config = load_json(DEFAULT_CONFIG_FILE)
    if not config:
        raise KitError("config.default.json이 없습니다. 키트를 다시 받으세요.")
    current = load_json(CONFIG_FILE) or {}
    for key in ("ollama_url",):
        if current.get(key):
            config[key] = current[key]
    speed, dimension = measure_speed(config)
    config["embed_chunks_per_sec"] = speed
    save_json(CONFIG_FILE, config)
    return speed, dimension


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
# 스킬
# ---------------------------------------------------------------------------

def skill_target():
    return home() / ".copilot" / "skills" / "local-rag"


def skill_files():
    return sorted(path for path in SKILL_SOURCE.rglob("*") if path.is_file() and not is_junk(path.name))


def skill_installed_state():
    target = skill_target()
    if not (target / "SKILL.md").is_file():
        return "없음"
    for source in skill_files():
        installed = target / source.relative_to(SKILL_SOURCE)
        if not installed.is_file() or installed.read_bytes() != source.read_bytes():
            return "옛 버전"
    return "최신"


def install_skill():
    target = skill_target()
    if target.exists() and skill_installed_state() != "최신":
        backup = BACKUP_DIR / f"skill-{timestamp()}"
        shutil.copytree(target, backup)
        say(f"  기존 스킬을 백업했습니다: {backup}")
    for source in skill_files():
        destination = target / source.relative_to(SKILL_SOURCE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return str(target)


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

def download(url, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    say(f"  받는 중: {target.relative_to(KIT) if KIT in target.parents else target}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as file:
            total = int(response.headers.get("Content-Length") or 0)
            done, shown = 0, -1
            for block in iter(lambda: response.read(1024 * 1024), b""):
                file.write(block)
                done += len(block)
                if total:
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


def command_prepare(args):
    targets = [item.strip() for item in args.os.split(",") if item.strip()]
    for target in targets:
        if target not in DOWNLOADS:
            raise KitError(f"--os에는 windows, mac, linux만 쓸 수 있습니다: {target}")
    say("사내망 반입 재료를 받습니다. 이 폴더(offline)에 모읍니다.")
    say(f"[1/3] sqlite-vec {SQLITE_VEC_VERSION} 설치 파일")
    ensure_wheels(targets)
    say("[2/3] Ollama, Python 설치 파일")
    for target in targets:
        for relative, url in DOWNLOADS[target]:
            path = OFFLINE / relative
            size = remote_size(url)
            if path.is_file() and size and path.stat().st_size == size:
                say(f"  이미 있음: {relative}")
                continue
            if free_bytes(OFFLINE) < size + 500 * 1024 ** 2:
                raise KitError(f"디스크 여유 공간이 부족합니다({size / 1024 ** 3:.1f}GB 필요).")
            download(url, path)
    say(f"[3/3] 임베딩 모델 {EMBED_MODEL}")
    source = ollama_models_dir()
    if ollama_running() and EMBED_MODEL in (ollama_models() or []) and model_files(source):
        say("  이 PC의 Ollama에 있는 모델 파일을 복사합니다.")
        copy_model(source, OFFLINE / "models")
    else:
        say("  모델 저장소에서 직접 받습니다(이 PC에는 아무것도 설치하지 않음).")
        download_model_from_registry(OFFLINE / "models")
    files = []
    for path in sorted(OFFLINE.rglob("*")):
        if path.is_file() and not is_junk(path.name) and path.suffix != ".part" and path.name != "MANIFEST.json":
            files.append({"path": path.relative_to(OFFLINE).as_posix(), "size": path.stat().st_size})
    save_json(OFFLINE / "MANIFEST.json", {
        "prepared_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "targets": targets, "model": EMBED_MODEL, "sqlite_vec": SQLITE_VEC_VERSION,
        "python_windows": PYTHON_WINDOWS_VERSION, "files": files,
    })
    total = sum(item["size"] for item in files)
    say("")
    say(f"반입 재료를 모두 모았습니다: {OFFLINE} (모두 {total / 1024 ** 3:.2f}GB)")
    say("이제 이 키트 폴더를 외장 드라이브에 복사하세요. Copilot에게 'E 드라이브에 반입용으로 복사해 줘'처럼 요청하면 됩니다.")
    return 0


# ---------------------------------------------------------------------------
# 복사
# ---------------------------------------------------------------------------

def copy_tree(source, destination, with_indexes=False):
    copied, total = 0, 0
    for directory, dirs, files in os.walk(source):
        relative_dir = Path(directory).relative_to(source)
        dirs[:] = [name for name in dirs if not is_junk(name) and not (relative_dir == Path(".") and name in COPY_SKIP)
                   and not (relative_dir == Path(".") and name == "indexes" and not with_indexes)
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


def command_copy_to(args):
    destination = Path(args.destination).expanduser()
    destination = destination.resolve() if destination.exists() else destination.absolute()
    if destination == KIT or KIT in destination.parents:
        raise KitError("복사할 곳이 지금 폴더이거나 그 안입니다. 다른 위치를 알려 주세요.")
    if destination.exists() and any(destination.iterdir()) and not (destination / "rag.py").exists():
        raise KitError(f"{destination}이 비어 있지 않습니다. 빈 폴더나 새 폴더 이름을 알려 주세요.")
    if args.with_indexes:
        say("색인(indexes)도 함께 복사합니다. 색인에는 문서 내용 조각이 들어 있으니 반출 규정을 확인하세요.")
    need = sum(path.stat().st_size for path in KIT.rglob("*") if path.is_file())
    if free_bytes(destination) < need:
        raise KitError(f"복사할 곳의 여유 공간이 부족합니다(최대 {need / 1024 ** 3:.1f}GB 필요).")
    say(f"복사합니다: {KIT} -> {destination}")
    copied, total = copy_tree(KIT, destination, args.with_indexes)
    say(f"파일 {copied}개({total / 1024 ** 3:.2f}GB)를 복사했습니다. 가상 환경(.venv), PC별 설정(config.json)은 옮기지 않았습니다.")
    say(f"복사한 폴더에서 설치하려면: {command_line(sys.executable, destination / 'setup' / 'kit.py', 'install')}")
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
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            finally:
                connection.close()
            rows.append((path.stem, metadata.get("source", ""), Path(metadata.get("source", "")).is_dir()))
        except sqlite3.Error:
            rows.append((path.stem, "(읽을 수 없음)", False))
    return rows


def check_items():
    items = []

    def add(name, ok, detail, fix=""):
        items.append((name, ok, detail, fix))

    problems = location_problems()
    add("키트 위치", None if problems else True, f"{KIT}" + (f" ({' '.join(problems)})" if problems else ""),
        f"홈 폴더로 복사해서 쓰세요. Copilot에게 '홈 폴더로 복사해서 설치해 줘'라고 요청하면 됩니다({suggested_home_folder()})."
        if problems else "")
    version = venv_state()
    problem = None if version else python_problem()
    add("Python", problem is None, f"{sys.version.split()[0]} ({sys.executable})" + (f": {problem}" if problem else ""),
        "AGENTS.md의 'Python 찾기' 순서로 알맞은 Python을 찾아 다시 실행하세요." if problem else "")
    add("sqlite-vec(.venv)", bool(version), f"sqlite-vec {version}" if version else "가상 환경이 없거나 이 PC에서 동작하지 않음",
        "이 폴더를 연 채로 '설치해 줘'라고 요청하세요." if not version else "")
    config = load_json(CONFIG_FILE)
    add("config.json", bool(config), "있음" if config else "없음", "" if config else "'설치해 줘'로 만듭니다.")
    running = ollama_running()
    add("Ollama", bool(running), f"{ollama_url()} 응답, 버전 {running}" if running else f"{ollama_url()} 응답 없음",
        "" if running else ("Ollama 앱을 실행하세요(Windows는 시작 메뉴, macOS는 응용 프로그램)." if find_ollama_app()
                            else "'설치해 줘'로 Ollama를 설치합니다."))
    models = ollama_models() if running else None
    has_model = bool(models and EMBED_MODEL in models)
    add("임베딩 모델", has_model if running else None, EMBED_MODEL + (" 있음" if has_model else " 없음" if running else " (Ollama 확인 뒤)"),
        "" if has_model else "'설치해 줘'로 반입 파일에서 복사하거나 받습니다.")
    configured = path_configured()
    on_path = shutil.which("rag")
    detail = "설정됨" if configured else "설정 안 됨"
    if configured and not on_path:
        detail += ", 지금 창에는 아직 반영 안 됨(VS Code를 완전히 종료했다가 다시 열면 반영)"
    add("rag 명령(PATH)", configured, detail, "" if configured else "'설치해 줘'로 등록합니다.")
    state = skill_installed_state()
    add("local-rag 스킬", state == "최신", f"{skill_target()} ({state})", "" if state == "최신" else "'설치해 줘'로 설치하거나 최신으로 바꿉니다.")
    rules, _ = vscode_rules_state()
    add("VS Code 자동 승인 규칙", True if rules != "없음" else None, rules,
        "" if rules != "없음" else "'설치해 줘'로 넣거나, 넣지 않으면 rag 명령마다 승인을 누르면 됩니다.")
    for name, source, exists in collection_sources():
        add(f"컬렉션 {name}", exists or None, source + ("" if exists else " (원본 폴더 없음)"),
            "" if exists else f"폴더를 옮겼다면 '/local-rag {name} 컬렉션의 원본 폴더를 <새 경로>로 옮겼어'라고 요청하세요.")
    return items


def command_check(_args=None):
    say(f"local-rag 점검 ({current_os()}, {platform.machine()})")
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

def install_plan():
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
        steps.append(("Ollama", "반입한 설치 파일로 설치(관리자 권한 없음)" if installer else "인터넷에서 받아 설치(관리자 권한 없음)", True))
    if EMBED_MODEL in (ollama_models() or []):
        steps.append(("임베딩 모델", "이미 있음", False))
    else:
        steps.append(("임베딩 모델", f"{'반입 파일에서 복사' if model_files(OFFLINE / 'models') else '인터넷에서 받음'} -> {ollama_models_dir()}", True))
    steps.append(("config.json", "이 PC의 임베딩 속도를 재서 저장", False))
    target = "사용자 환경 변수 Path와 RAG_HOME" if IS_WINDOWS else str(shell_rc_file())
    steps.append(("rag 명령 등록", "이미 됨" if path_configured() else f"{target}에 {KIT / 'bin'} 추가", not path_configured()))
    state = skill_installed_state()
    steps.append(("local-rag 스킬", "최신, 그대로 둠" if state == "최신" else f"{skill_target()}에 {'설치' if state == '없음' else '최신으로 교체(기존 것은 백업)'}",
                  state != "최신"))
    rules, missing = vscode_rules_state()
    if rules == "VS Code 없음":
        steps.append(("VS Code 자동 승인 규칙", "VS Code 사용자 설정이 없어 건너뜀", False))
    else:
        steps.append(("VS Code 자동 승인 규칙", "이미 있음" if rules == "있음" else
                      f"{', '.join(str(path) for path in missing)}에 규칙 3개 추가(검색, 목록, 미리보기만 자동 승인)", rules != "있음"))
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
    if not args.yes:
        say("설치 계획(아직 아무것도 바꾸지 않았습니다)")
        for number, (name, action, changes_pc) in enumerate(install_plan(), 1):
            say(f"{number}. {name}: {action}" + (" [PC 설정 변경]" if changes_pc else ""))
        say("")
        say("진행하려면 같은 명령에 --yes를 붙여 실행하세요. 자동 승인 규칙을 넣지 않으려면 --no-vscode를 함께 붙이세요.")
        return 0
    say(f"[1/{TOTAL_STEPS}] 가상 환경과 sqlite-vec")
    version = venv_state() or make_venv()
    say(f"  sqlite-vec {version}")
    say(f"[2/{TOTAL_STEPS}] Ollama")
    if not ollama_running():
        app = find_ollama_app()
        if app:
            say("  Ollama 앱을 실행합니다.")
            start_ollama_app(app)
            if not wait_for(ollama_running, 60):
                raise KitError("Ollama 앱이 응답하지 않습니다. 앱을 직접 실행한 뒤 다시 요청하세요.")
        else:
            install_ollama()
    say(f"  버전 {ollama_running()}")
    say(f"[3/{TOTAL_STEPS}] 임베딩 모델 {EMBED_MODEL}")
    say(f"  {ensure_model()}")
    say(f"[4/{TOTAL_STEPS}] config.json과 속도 측정")
    speed, dimension = write_config()
    say(f"  초당 {speed}개 조각, 벡터 {dimension}차원")
    say(f"[5/{TOTAL_STEPS}] rag 명령 등록")
    say(f"  {configure_path()}")
    say(f"[6/{TOTAL_STEPS}] local-rag 스킬")
    say(f"  {install_skill()}")
    say(f"[7/{TOTAL_STEPS}] VS Code 자동 승인 규칙")
    if args.no_vscode:
        say("  건너뜀(--no-vscode)")
    else:
        done, manual = install_vscode_rules()
        for path in done:
            say(f"  {path}")
        for item in manual:
            say(f"  직접 넣어야 함: {item}")
        if manual:
            say("  Copilot에게 VS Code 사용자 설정에 아래 규칙을 넣어 달라고 요청하세요:")
            for rule, value in APPROVE_RULES:
                say(f"    {json.dumps(rule)}: {json.dumps(value)}")
        if not done and not manual:
            say("  VS Code 사용자 설정 폴더가 없어 건너뜀")
    say(f"[8/{TOTAL_STEPS}] 자체 시험")
    result = subprocess.run([str(venv_python()), str(KIT / "tests" / "selftest.py")])
    if result.returncode != 0:
        raise KitError("자체 시험에 실패했습니다. 위 출력의 [실패] 줄을 확인하세요.")
    say("")
    say("설치를 마쳤습니다.")
    say("- VS Code를 완전히 종료했다가 다시 열어야 rag 명령과 local-rag 스킬이 보입니다.")
    say("- 그다음 아무 프로젝트에서나 새 대화를 열고 '/local-rag 목록 보여 줘'로 확인하세요.")
    return 0


def command_uninstall(args):
    if not args.yes:
        say("지울 것: rag 명령 등록(PATH, RAG_HOME), local-rag 스킬. Ollama, 모델, 이 폴더의 색인은 그대로 둡니다.")
        say("지우려면 --yes를 붙이세요.")
        return 0
    say(f"rag 명령 등록 해제: {configure_path(remove_only=True)}")
    target = skill_target()
    if target.exists():
        backup = BACKUP_DIR / f"skill-{timestamp()}"
        shutil.copytree(target, backup)
        shutil.rmtree(target)
        say(f"local-rag 스킬을 지웠습니다(백업: {backup}).")
    say("VS Code 자동 승인 규칙은 그대로 두었습니다. rag 명령이 없으면 아무 일도 하지 않습니다.")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="kit.py", description="local-rag 설치 도우미")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    install = commands.add_parser("install")
    install.add_argument("--yes", action="store_true")
    install.add_argument("--here", action="store_true", help="외장 드라이브 등 지금 위치에 그대로 설치")
    install.add_argument("--no-vscode", action="store_true")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--os", default="windows," + current_os() if current_os() != "windows" else "windows")
    copy = commands.add_parser("copy-to")
    copy.add_argument("destination")
    copy.add_argument("--with-indexes", action="store_true")
    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    handlers = {"check": command_check, "install": command_install, "prepare": command_prepare,
                "copy-to": command_copy_to, "uninstall": command_uninstall}
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
