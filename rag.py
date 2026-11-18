#!/usr/bin/env python3
"""로컬 RAG 명령 도구 rag.

문서 폴더를 컬렉션으로 색인하고, 질문과 의미가 가까운 조각을 찾는다.
Python 표준 라이브러리와 sqlite-vec만 사용하며, 임베딩은 이 PC의 Ollama가 만든다.
사용법은 USAGE.md를 본다.
"""
import argparse
import contextlib
import fnmatch
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TOOL_VERSION = "2.1.0"
ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
MODELS_FILE = ROOT / "models.json"
# 시험할 때만 RAG_INDEX_DIR로 색인 위치를 바꾼다.
INDEX_DIR = Path(os.environ["RAG_INDEX_DIR"]).expanduser().resolve() if os.environ.get("RAG_INDEX_DIR") else ROOT / "indexes"
JOB_DIR = INDEX_DIR / ".jobs"  # 색인 작업의 잠금과 진행 기록(setup/joblock.py)
IS_WINDOWS = os.name == "nt"

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "out", "coverage"}
# 운영체제가 만드는 숨은 폴더와 파일. 건너뛴 목록에도 세지 않는다.
JUNK_DIRS = {".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems", "$RECYCLE.BIN", "System Volume Information"}
JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini", "ehthumbs.db", "icon\r"}
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
DEFAULT_EXTENSIONS = {".md", ".markdown", ".txt"}
MAX_FILE_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 1000
EMBED_BATCH_SIZE = 16
# 자체 시험만 RAG_AUTO_REFRESH_LIMIT로 한도를 바꾼다(느린 PC에서도 같은 결과가 나오도록).
AUTO_REFRESH_LIMIT_SECONDS = int(os.environ.get("RAG_AUTO_REFRESH_LIMIT") or 20)
TEST_DELAY_SECONDS = float(os.environ.get("RAG_TEST_DELAY") or 0)  # 자체 시험에서 색인을 일부러 느리게 할 때만
NAME_PATTERN = re.compile(r"^[a-z0-9가-힣-]+$")
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
CONFIG_KEYS = ("embed_model", "ollama_url", "num_ctx", "keep_alive", "query_instruction", "embed_chunks_per_sec")
INSTALL_HINT = ("로컬 RAG 키트 폴더(local-rag 또는 github-copilot-local-rag-main)를 AI 도구(VS Code의 Copilot, Claude Code 등)에서 "
                "열고 '설치해 줘'라고 요청하세요.")
# 컬렉션 이름의 프로젝트를 찾을 때 보는 표시(가장 가까운 상위 폴더의 것)
PROJECT_MARKERS = (".git", ".github", ".vscode", ".agents", ".claude", ".idea", "AGENTS.md", "CLAUDE.md",
                   "package.json", "pyproject.toml")
NAME_BASE_LIMIT = 40


sys.path.insert(0, str(ROOT / "setup"))
import joblock  # noqa: E402


class RagError(Exception):
    pass


# ---------------------------------------------------------------------------
# 경로와 이름
# ---------------------------------------------------------------------------

def nfc(text):
    """한글 파일 이름을 한 가지 표기(NFC)로 맞춘다. macOS와 외장 드라이브는 NFD로 돌려주기도 한다."""
    return unicodedata.normalize("NFC", text)


def path_key(path, windows=IS_WINDOWS):
    """두 폴더 경로가 같은지 비교할 때 쓰는 값. 한글 표기와 Windows의 대소문자 차이를 없앤다."""
    text = nfc(str(path))
    if windows:
        text = text.replace("/", "\\").rstrip("\\").lower()
    else:
        text = text.rstrip("/") or "/"
    return text


def windows_long_path(text, force=False):
    """Windows에서 260자가 넘는 경로도 열 수 있게 \\\\?\\ 접두사를 붙인다. force면 길이와 상관없이 붙인다."""
    if text.startswith("\\\\?\\") or (len(text) < 240 and not force):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def os_path(path, force=False):
    text = str(path)
    return windows_long_path(text, force) if IS_WINDOWS else text


def find_on_disk(root, actual):
    """디스크에 있는 실제 상대 경로를 찾는다. NTFS처럼 이름을 바꾸지 않는 곳에서는
    NFC로 적은 이름과 디스크의 NFD 이름이 다를 수 있어 폴더를 훑어 맞춘다. 없으면 None."""
    root = Path(root)
    if os.path.exists(os_path(root / actual)):
        return actual
    current, parts = root, []
    for part in actual.split("/"):
        target = nfc(part)
        try:
            names = os.listdir(os_path(current))
        except OSError:
            return None
        match = next((name for name in names if nfc(name) == target), None)
        if match is None:
            return None
        parts.append(match)
        current = current / match
    return "/".join(parts)


def is_junk(name):
    lowered = name.lower()
    return name.startswith("._") or lowered in JUNK_FILES or name.startswith("~$") or name.startswith(".~lock.")


def sanitize_name(text):
    text = nfc(text).strip().lower()
    text = re.sub(r"[\s_.]+", "-", text)
    text = re.sub(r"[^a-z0-9가-힣-]", "", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def validate_name(name):
    if not name or not NAME_PATTERN.fullmatch(name):
        raise RagError("컬렉션 이름은 영문 소문자, 숫자, 한글, 하이픈만 사용할 수 있습니다.")
    return name


def matches_any(path, patterns):
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern) for pattern in patterns)


# ---------------------------------------------------------------------------
# 설정과 DB
# ---------------------------------------------------------------------------

def load_config():
    if not CONFIG_FILE.is_file():
        raise RagError(f"config.json이 없습니다. 이 PC에는 설치가 끝나지 않았습니다. {INSTALL_HINT}")
    try:
        with CONFIG_FILE.open(encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RagError(f"config.json을 읽을 수 없습니다: {error}") from error
    for key in CONFIG_KEYS:
        if key not in config:
            raise RagError(f"config.json에 {key} 설정이 없습니다. {INSTALL_HINT}")
    return config


def open_db(path):
    connection = sqlite3.connect(os_path(path), timeout=30)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        if not hasattr(connection, "enable_load_extension"):
            raise RagError("이 Python은 SQLite 확장 불러오기를 지원하지 않습니다. " + INSTALL_HINT)
        try:
            import sqlite_vec
        except ImportError as error:
            raise RagError("sqlite-vec가 설치되어 있지 않습니다. " + INSTALL_HINT) from error
        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        except sqlite3.OperationalError as error:
            raise RagError(f"sqlite-vec 확장 파일을 불러오지 못했습니다(보안 정책으로 막혔을 수 있습니다): {error}") from error
        finally:
            connection.enable_load_extension(False)
    except BaseException:
        connection.close()
        raise
    return connection


def db_metadata(connection):
    try:
        return dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.OperationalError as error:
        raise RagError(f"컬렉션 데이터베이스를 읽을 수 없습니다: {error}") from error


def update_metadata(connection, key, value):
    connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", (key, value))
    connection.commit()


def collection_model(name):
    try:
        connection = open_db(INDEX_DIR / f"{name}.db")
    except (sqlite3.Error, RagError):
        return None
    try:
        return db_metadata(connection).get("model")
    finally:
        connection.close()


def collection_paths():
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(path for path in INDEX_DIR.glob("*.db") if not path.name.startswith("."))


def get_collection(name):
    validate_name(name)
    path = INDEX_DIR / f"{name}.db"
    if not path.is_file():
        if joblock.is_running(JOB_DIR, name):
            raise RagError(f"컬렉션 '{name}'을 지금 만들기 시작했습니다. 몇 초 뒤 같은 명령을 다시 실행하세요.")
        raise RagError(f"컬렉션 '{name}'이 없습니다. `rag list`로 이름을 확인하거나 `rag index <폴더>`로 먼저 만드세요.")
    connection = open_db(path)
    metadata = db_metadata(connection)
    if "dimension" not in metadata:
        connection.close()
        raise RagError(f"컬렉션 '{name}'은 만들다 멈춘 상태입니다. `rag remove {name} --yes`로 지운 뒤 다시 만드세요.")
    return path, connection, metadata


def list_collections():
    rows = []
    for path in collection_paths():
        try:
            connection = open_db(path)
            try:
                metadata = db_metadata(connection)
                file_count = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
                chunk_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            finally:
                connection.close()
            rows.append((path.stem, metadata, file_count, chunk_count))
        except (sqlite3.Error, RagError):
            continue
    return rows


def find_collection_for_source(source):
    wanted = path_key(source)
    for name, metadata, _, _ in list_collections():
        if path_key(metadata.get("source", "")) == wanted:
            return name
    return None


def project_root(source):
    """문서 폴더를 가진 프로젝트 폴더(가장 가까운 상위 폴더 중 .git, AGENTS.md 같은 표시가 있는 곳). 없으면 None."""
    source = Path(source)
    stop = Path.home()
    current = source
    while True:
        if path_key(current) == path_key(stop) or current.parent == current:
            return None
        if any((current / marker).exists() for marker in PROJECT_MARKERS):
            return current
        current = current.parent


def name_base(source):
    source = Path(source)
    root = project_root(source)
    if root is None:
        parts = [source.parent.name, source.name]
    elif path_key(root) == path_key(source):
        parts = [source.name]
    else:
        parts = [root.name, *source.relative_to(root).parts]
    base = "-".join(part for part in (sanitize_name(item) for item in parts) if part) or "docs"
    if len(base) > NAME_BASE_LIMIT:
        base = base[:NAME_BASE_LIMIT].rsplit("-", 1)[0] or base[:NAME_BASE_LIMIT]
    return base


def suggest_name(source):
    """'프로젝트-폴더-해시' 이름을 정한다. 해시는 폴더 경로로 만들어서, 이름이 같은 다른 프로젝트와 겹치지 않는다.
    같은 폴더에는 언제나 같은 이름이 나온다."""
    source = Path(source)
    taken = {name: metadata.get("source", "") for name, metadata, _, _ in list_collections()}
    digest = hashlib.sha1(path_key(source).encode("utf-8")).hexdigest()
    base = name_base(source)
    for length in (4, 6, 8, 40):
        candidate = f"{base}-{digest[:length]}"
        if candidate not in taken or path_key(taken[candidate]) == path_key(source):
            return candidate
    return f"{base}-{digest}"


def create_database(path, name, description, source, config, auto_refresh=True):
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RagError(f"컬렉션 DB가 이미 있습니다: {path}")
    _, dimension = ollama_embed(config, ["초기 벡터 차원 확인"])
    # 다른 이름으로 다 만든 뒤 바꿔 넣는다. 만드는 중에 검색하거나 목록을 봐도 반쯤 만든 DB가 보이지 않게 한다.
    temporary = path.with_name(f".{path.stem}-new.db")
    remove_db_files(temporary)
    connection = open_db(temporary)
    try:
        connection.executescript(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL);"
            "CREATE TABLE chunks (id INTEGER PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL, modified TEXT NOT NULL, body TEXT NOT NULL);"
            "CREATE INDEX chunks_path ON chunks(path);"
        )
        connection.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dimension}] distance_metric=cosine)")
        metadata = {
            "name": name,
            "description": description,
            "source": str(source),
            "model": config["embed_model"],
            "dimension": str(dimension),
            "auto_refresh": "on" if auto_refresh else "off",
            "updated_at": "",
            "tool_version": TOOL_VERSION,
        }
        connection.executemany("INSERT INTO metadata(key, value) VALUES(?, ?)", metadata.items())
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
        for suffix in ("-wal", "-shm"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)  # Windows 보안 프로그램이 새 파일을 잠깐 잡고 있을 때
    except BaseException:
        connection.close()
        remove_db_files(temporary)
        raise
    return open_db(path)


def remove_db_files(path):
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def stored_files(connection):
    return {row[0]: {"size": row[1], "mtime_ns": row[2], "sha256": row[3]}
            for row in connection.execute("SELECT path, size, mtime_ns, sha256 FROM files")}


def normalize_stored_paths(connection):
    """예전에 NFD로 저장된 경로를 NFC로 바꾼다. 같은 파일이 두 번 들어가 있으면 하나만 남긴다."""
    rows = connection.execute("SELECT path FROM files").fetchall()
    odd = [row[0] for row in rows if row[0] != nfc(row[0])]
    if not odd:
        return 0
    existing = {row[0] for row in rows}
    connection.execute("BEGIN")
    try:
        for path in odd:
            target = nfc(path)
            if target in existing:
                delete_file_rows(connection, path)
            else:
                connection.execute("UPDATE files SET path=? WHERE path=?", (target, path))
                connection.execute("UPDATE chunks SET path=? WHERE path=?", (target, path))
                existing.add(target)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return len(odd)


def normalize_model(model):
    """Ollama는 태그 없는 이름을 '<이름>:latest'로 저장한다."""
    model = (model or "").strip()
    return model if not model or ":" in model.rsplit("/", 1)[-1] else model + ":latest"


def model_catalog():
    try:
        with MODELS_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {"default": "", "models": []}


def model_profile(model):
    """모델마다 질문과 문서를 임베딩하는 형식이 다르다. 목록에 없는 모델은 형식 없이 쓴다."""
    for item in model_catalog().get("models", []):
        if item.get("name") == model:
            return item
    return {"name": model, "query": "{question}", "document": "{title}\n{text}"}


def fill(template, values):
    return re.sub(r"\{(\w+)\}", lambda match: values.get(match.group(1), match.group(0)), template)


def bind_model(config, model=None):
    """config를 특정 모델용으로 바꾼 복사본. 속도는 모델별로 잰 값이 있으면 그 값을 쓴다."""
    model = model or config["embed_model"]
    speeds = config.get("model_speeds") or {}
    speed = speeds.get(model) or (config["embed_chunks_per_sec"] if model == config["embed_model"] else
                                  config["embed_chunks_per_sec"] * 0.8)
    return dict(config, embed_model=model, embed_chunks_per_sec=speed)


# ---------------------------------------------------------------------------
# 파일 찾기와 읽기
# ---------------------------------------------------------------------------

def run_git(root, *args, timeout=30):
    flags = {"creationflags": 0x08000000} if IS_WINDOWS else {}
    return subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          check=False, timeout=timeout, **flags)


def path_is_git_repo(root):
    try:
        return run_git(root, "rev-parse", "--show-toplevel", timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def candidate_paths(root):
    """원본 폴더 안의 파일 목록(원본 기준 상대 경로, 디스크에 있는 이름 그대로)."""
    if path_is_git_repo(root):
        try:
            result = run_git(root, "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        except (OSError, subprocess.SubprocessError) as error:
            raise RagError(f"git 파일 목록을 가져오지 못했습니다: {error}") from error
        if result.returncode == 0:
            return [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item]
    walk_root = os_path(root, force=True)
    found = []
    try:
        for directory, dirs, files in os.walk(walk_root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS and name not in JUNK_DIRS and not name.startswith("._")]
            for name in files:
                relative = os.path.relpath(os.path.join(directory, name), walk_root)
                found.append(relative.replace(os.sep, "/"))
    except OSError as error:
        raise RagError(f"폴더를 읽을 수 없습니다: {error}") from error
    return found


def excluded_reason(relative, excludes):
    parts = relative.split("/")
    lowered = parts[-1].lower()
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return "제외 폴더"
    if lowered == ".env" or lowered.startswith(".env.") or lowered.endswith(SECRET_SUFFIXES):
        return "비밀 정보 파일"
    if excludes and matches_any(relative, excludes):
        return "사용자 제외 패턴"
    return None


def discover_files(root, extensions, excludes, patterns=None):
    """색인 대상 파일을 찾는다. 내용은 읽지 않고 크기와 수정 시각만 본다."""
    records, skipped, protected = {}, {}, set()

    def skip(extension, reason):
        skipped[(extension, reason)] = skipped.get((extension, reason), 0) + 1

    for actual in candidate_paths(root):
        actual = actual.replace("\\", "/")
        parts = actual.split("/")
        if any(is_junk(part) for part in parts) or any(part in JUNK_DIRS for part in parts[:-1]):
            continue
        key = nfc(actual)
        if patterns and not matches_any(key, patterns):
            continue
        extension = Path(key).suffix.lower() or "(확장자 없음)"
        reason = excluded_reason(key, excludes)
        if reason:
            skip(extension, reason)
            continue
        if extension not in extensions:
            skip(extension, "선택한 확장자에서 제외")
            continue
        try:
            stat = os.stat(os_path(Path(root) / actual))
        except FileNotFoundError:
            continue
        except PermissionError:
            skip(extension, "권한 없음")
            protected.add(key)
            continue
        except OSError:
            skip(extension, "열 수 없음(경로 길이 등)")
            protected.add(key)
            continue
        if stat.st_size > MAX_FILE_SIZE:
            skip(extension, "1MB 초과")
            continue
        if key in records:
            skip(extension, "한글 표기만 다른 같은 이름")
            continue
        records[key] = {"path": key, "actual": actual, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return records, skipped, protected


def load_text(root, record):
    """파일을 읽어 본문과 해시를 채운다. 읽을 수 없으면 (이유, 보호 여부)를 돌려준다."""
    try:
        with open(os_path(Path(root) / record["actual"]), "rb") as file:
            data = file.read(MAX_FILE_SIZE + 1)
    except PermissionError:
        return "권한 없음", True
    except FileNotFoundError:
        return "사라짐", False
    except OSError:
        return "열 수 없음(경로 길이 등)", True
    if len(data) > MAX_FILE_SIZE:
        return "1MB 초과", False
    if b"\0" in data[:8192]:
        return "바이너리 파일", False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp949")
        except UnicodeDecodeError:
            return "UTF-8/CP949로 읽을 수 없음", False
    record["text"] = text
    record["size"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    return None, False


# ---------------------------------------------------------------------------
# 조각 나누기
# ---------------------------------------------------------------------------

def split_long(text):
    """1,000자 이하 조각으로 나눈다. 짧은 문단은 한도 안에서 합친다."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= MAX_CHUNK_SIZE:
        return [text]
    units = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= MAX_CHUNK_SIZE:
            units.append((paragraph, "\n\n"))
            continue
        joiner = "\n\n"
        for line in paragraph.splitlines():
            line = line.rstrip()
            while len(line) > MAX_CHUNK_SIZE:
                units.append((line[:MAX_CHUNK_SIZE], joiner))
                line = line[MAX_CHUNK_SIZE:]
                joiner = "\n"
            if line.strip():
                units.append((line, joiner))
                joiner = "\n"
    result, current = [], ""
    for unit, joiner in units:
        if current and len(current) + len(joiner) + len(unit) > MAX_CHUNK_SIZE:
            result.append(current)
            current = unit
        else:
            current = f"{current}{joiner}{unit}" if current else unit
    if current:
        result.append(current)
    return result


def document_chunks(text, relative):
    """마크다운은 제목(#, ##, ###) 단위로, 그 밖의 텍스트는 문단 단위로 나눈다. 코드 블록 안의 #은 제목이 아니다."""
    markdown = Path(relative).suffix.lower() in {".md", ".markdown"}
    sections, titles, lines = [], [], []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if markdown and (stripped.startswith("```") or stripped.startswith("~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else (fence or marker)
            lines.append(line)
            continue
        heading = HEADING_PATTERN.match(line) if markdown and fence is None else None
        if heading:
            if lines:
                sections.append((titles.copy(), "\n".join(lines)))
                lines = []
            level = len(heading.group(1))
            titles = titles[:level - 1] + [heading.group(2).strip()]
        else:
            lines.append(line)
    if lines:
        sections.append((titles.copy(), "\n".join(lines)))
    output = []
    for section_titles, body in sections:
        heading_path = " > ".join(section_titles)
        for piece in split_long(body):
            output.append((heading_path, piece))
    return output


def embedding_text(relative, title, body, model=None):
    filename = nfc(relative.rsplit("/", 1)[-1])
    heading = f"{filename} > {title}" if title else filename
    template = model_profile(model)["document"] if model else "{title}\n{text}"
    return fill(template, {"title": heading, "text": body})


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

OLLAMA_STARTED = []


def start_ollama(config):
    """Ollama가 꺼져 있으면 켠다(앱, 응답이 없으면 서버). 한 번만 시도하고, 안내는 표준 오류로 쓴다(--json 출력 보호)."""
    if OLLAMA_STARTED:
        return False
    OLLAMA_STARTED.append(True)
    host = urllib.parse.urlparse(config["ollama_url"]).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        return False
    import kit
    app = kit.find_ollama_app()
    if app is None:
        raise RagError("이 PC에 Ollama가 없습니다. 로컬 RAG 키트 폴더를 AI 도구에서 열고 '설치해 줘'라고 요청하세요.")
    print("Ollama가 꺼져 있어 켭니다(1분쯤 걸릴 수 있음).", file=sys.stderr, flush=True)
    with contextlib.redirect_stdout(sys.stderr):
        return bool(kit.bring_up_ollama(app, 40))


def ollama_embed(config, texts, retry=True):
    request = urllib.request.Request(
        config["ollama_url"].rstrip("/") + "/api/embed",
        data=json.dumps({
            "model": config["embed_model"],
            "input": texts,
            "keep_alive": config["keep_alive"],
            "options": {"num_ctx": config["num_ctx"]},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=300) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RagError(f"임베딩 모델 {config['embed_model']}이 이 PC의 Ollama에 없습니다. "
                           f"`rag models --add {config['embed_model']}`로 받은 뒤 같은 명령을 다시 실행하세요.") from error
        raise RagError(f"Ollama가 오류를 돌려줬습니다({error.code}). 잠시 뒤 다시 시도하세요.") from error
    except (urllib.error.URLError, ConnectionError) as error:
        if retry and start_ollama(config):
            return ollama_embed(config, texts, retry=False)
        raise RagError("Ollama가 꺼져 있고 켜지도 못했습니다. `rag check`를 실행해 Ollama 항목의 다음에 할 일을 확인하세요.") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise RagError(f"Ollama 응답을 처리하지 못했습니다: {error}") from error
    vectors = payload.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts) or not vectors:
        raise RagError("Ollama가 예상한 수의 임베딩 벡터를 돌려주지 않았습니다.")
    dimension = len(vectors[0])
    for vector in vectors:
        if len(vector) != dimension or not dimension or any(
                not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
            raise RagError("임베딩 벡터의 차원이 다르거나 NaN, 무한대 값이 들어 있습니다.")
    return vectors, dimension


def query_vector(config, question):
    template = model_profile(config["embed_model"])["query"]
    text = fill(template, {"instruction": config.get("query_instruction", ""), "question": nfc(question)})
    vectors, dimension = ollama_embed(config, [text])
    return vectors[0], dimension


# ---------------------------------------------------------------------------
# 갱신 계획과 적용
# ---------------------------------------------------------------------------

class Plan:
    def __init__(self):
        self.changes = []      # 다시 임베딩할 파일
        self.restamps = []     # 내용은 같고 크기나 수정 시각만 바뀐 파일
        self.deletions = []    # 색인에서 지울 파일
        self.skipped = {}
        self.held = 0          # 절반 넘게 사라져 삭제를 보류한 수

    def chunk_count(self):
        return sum(len(document_chunks(record["text"], record["path"])) for record in self.changes)


def collection_settings(metadata):
    extensions = parse_extensions(metadata.get("extensions"))
    excludes = json.loads(metadata.get("excludes", "[]") or "[]")
    return extensions, excludes


def explicit_keys(root, files):
    keys = []
    root_resolved = Path(root).resolve()
    for item in files:
        candidate = Path(item).expanduser()
        absolute = (candidate if candidate.is_absolute() else root_resolved / candidate).resolve()
        try:
            relative = absolute.relative_to(root_resolved).as_posix()
        except ValueError:
            relative_text = os.path.relpath(nfc(str(absolute)), nfc(str(root_resolved)))
            if relative_text.startswith(".."):
                raise RagError(f"파일이 컬렉션 원본 폴더 밖에 있습니다: {item}")
            relative = relative_text.replace(os.sep, "/")
        keys.append((nfc(relative), relative))
    return keys


def plan_update(connection, root, extensions, excludes, only=None, files=None, rebuild=False, prune=False):
    stored = stored_files(connection)
    plan = Plan()
    if files is not None:
        for key, actual in explicit_keys(root, files):
            actual = find_on_disk(root, actual) or actual
            record = {"path": key, "actual": actual}
            try:
                stat = os.stat(os_path(Path(root) / actual))
            except FileNotFoundError:
                if key in stored:
                    plan.deletions.append(key)
                continue
            reason = excluded_reason(key, excludes)
            if reason:
                raise RagError(f"요청한 파일은 색인할 수 없습니다({reason}): {key}")
            record["size"], record["mtime_ns"] = stat.st_size, stat.st_mtime_ns
            reason, _ = load_text(root, record)
            if reason:
                raise RagError(f"요청한 파일을 읽을 수 없습니다({reason}): {key}")
            plan.changes.append(record)
        return plan
    records, plan.skipped, protected = discover_files(root, extensions, excludes, only)
    relevant = {key for key in stored if not only or matches_any(key, only)}
    included = set()
    for key in sorted(records):
        record = records[key]
        previous = stored.get(key)
        if previous and not rebuild and previous["size"] == record["size"] and previous["mtime_ns"] == record["mtime_ns"]:
            included.add(key)
            continue
        reason, keep = load_text(root, record)
        if reason:
            extension = Path(key).suffix.lower()
            plan.skipped[(extension, reason)] = plan.skipped.get((extension, reason), 0) + 1
            if keep:
                protected.add(key)
            continue
        included.add(key)
        if previous and not rebuild and previous["sha256"] == record["sha256"]:
            plan.restamps.append(record)
        else:
            plan.changes.append(record)
    deletions = sorted(key for key in relevant if key not in included and key not in protected)
    if not only and deletions and len(deletions) > len(stored) / 2 and not prune:
        plan.held = len(deletions)
        deletions = []
    plan.deletions = deletions
    return plan


def delete_file_rows(connection, relative):
    ids = [row[0] for row in connection.execute("SELECT id FROM chunks WHERE path=?", (relative,))]
    connection.executemany("DELETE FROM vec_chunks WHERE rowid=?", ((rowid,) for rowid in ids))
    connection.execute("DELETE FROM chunks WHERE path=?", (relative,))
    connection.execute("DELETE FROM files WHERE path=?", (relative,))


def embed_record(config, record, on_batch=None):
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record["mtime_ns"] / 1e9))
    chunks = document_chunks(record["text"], record["path"])
    vectors, dimension = [], None
    for offset in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[offset:offset + EMBED_BATCH_SIZE]
        result, current = ollama_embed(config, [embedding_text(record["path"], title, body, config["embed_model"])
                                                for title, body in batch])
        if dimension is not None and dimension != current:
            raise RagError("임베딩 차원이 요청마다 달라졌습니다.")
        dimension = current
        vectors.extend(result)
        if on_batch:
            on_batch(len(batch))
    return modified, chunks, vectors, dimension


class Progress:
    """색인 진행 상황. 화면(터미널)에서는 한 줄을 고쳐 쓰고, AI 도구처럼 파이프로 읽으면 10%마다 또는 15초마다 한 줄씩 쓴다."""

    def __init__(self, files, chunks, enabled=True):
        self.files, self.chunks, self.enabled = files, max(chunks, 1), enabled
        self.done_files = self.done_chunks = 0
        self.started = self.printed_at = time.time()
        self.bucket = -1
        self.interactive = sys.stderr.isatty()

    def add(self, chunks=0, files=0):
        self.done_chunks += chunks
        self.done_files += files
        if not self.enabled:
            return
        percent = min(self.done_chunks * 100 // self.chunks, 100)
        elapsed = time.time() - self.started
        left = ""
        if 0 < self.done_chunks < self.chunks and elapsed >= 5:
            left = f", 남은 시간 약 {joblock.duration(elapsed / self.done_chunks * (self.chunks - self.done_chunks))}"
        bar = "#" * (percent // 5) + "-" * (20 - percent // 5)
        line = (f"[{bar}] {percent:3d}% 조각 {min(self.done_chunks, self.chunks)}/{self.chunks}, "
                f"파일 {self.done_files}/{self.files}, 경과 {joblock.duration(elapsed)}{left}")
        if self.interactive:
            print("\r" + line + "   ", end="", file=sys.stderr, flush=True)
        elif percent // 10 != self.bucket or time.time() - self.printed_at >= 15 or self.done_files == self.files:
            self.bucket = percent // 10
            self.printed_at = time.time()
            print(line, file=sys.stderr, flush=True)

    def close(self):
        if self.enabled and self.interactive and self.files:
            print(file=sys.stderr)


def apply_plan(connection, config, plan, show_progress=True):
    """계획대로 저장한다. 파일 하나가 끝날 때마다 저장하므로 멈춰도 같은 명령으로 이어서 할 수 있다."""
    dimension = int(db_metadata(connection)["dimension"])
    done = 0
    progress = Progress(len(plan.changes), plan.chunk_count() if plan.changes else 0, show_progress and bool(plan.changes))
    for record in plan.changes:
        modified, chunks, vectors, current = embed_record(config, record, progress.add)
        if chunks and current != dimension:
            raise RagError("임베딩 벡터 차원이 컬렉션과 다릅니다. 모델을 확인하고 --rebuild로 다시 만드세요.")
        connection.execute("BEGIN")
        try:
            delete_file_rows(connection, record["path"])
            for (title, body), vector in zip(chunks, vectors):
                cursor = connection.execute("INSERT INTO chunks(path, title, modified, body) VALUES(?, ?, ?, ?)",
                                            (record["path"], title, modified, body))
                connection.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES(?, ?)", (cursor.lastrowid, json.dumps(vector)))
            connection.execute("INSERT INTO files(path, size, mtime_ns, sha256) VALUES(?, ?, ?, ?)",
                               (record["path"], record["size"], record["mtime_ns"], record["sha256"]))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        done += 1
        progress.add(files=1)
        if TEST_DELAY_SECONDS:
            time.sleep(TEST_DELAY_SECONDS)
    progress.close()
    if plan.restamps or plan.deletions:
        connection.execute("BEGIN")
        try:
            for record in plan.restamps:
                connection.execute("UPDATE files SET size=?, mtime_ns=? WHERE path=?",
                                   (record["size"], record["mtime_ns"], record["path"]))
            for relative in plan.deletions:
                delete_file_rows(connection, relative)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    if done or plan.deletions:
        update_metadata(connection, "updated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    return done


def expected_seconds(config, chunks):
    return chunks / max(float(config["embed_chunks_per_sec"]), 0.001)


def print_skipped(skipped, stream=sys.stdout):
    for (extension, reason), count in sorted(skipped.items()):
        print(f"건너뜀 {extension} / {reason}: {count}개", file=stream)


def run_update(connection, config, name, root, extensions, excludes, only=None, files=None, rebuild=False,
               prune=False, dry_run=False):
    if not Path(root).is_dir():
        print(f"경고: 원본 폴더를 찾을 수 없어 아무것도 지우지 않았습니다: {root}\n"
              f"폴더를 옮겼다면 `rag move {name} <새 경로>`로 알려 주세요.", file=sys.stderr)
        return 0
    normalize_stored_paths(connection)
    plan = plan_update(connection, root, extensions, excludes, only, files, rebuild, prune)
    chunks = plan.chunk_count()
    if plan.held:
        print(f"경고: 색인 파일 중 {plan.held}개(절반 넘게)가 원본에서 사라져 삭제를 보류했습니다. "
              f"폴더를 옮겼다면 `rag move {name} <새 경로>`, 정말 지운 것이면 --prune을 붙이세요.", file=sys.stderr)
    if dry_run:
        print(f"다시 임베딩할 파일: {len(plan.changes)}개, 조각: {chunks}개")
        print(f"지울 파일: {len(plan.deletions)}개, 예상 시간: {expected_seconds(config, chunks):.1f}초")
        print_skipped(plan.skipped)
        return 0
    done = apply_plan(connection, config, plan)
    print(f"다시 임베딩한 파일: {done}개, 지운 파일: {len(plan.deletions)}개")
    print_skipped(plan.skipped)
    files = connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunks_total = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"컬렉션 '{name}': 파일 {files}개, 조각 {chunks_total}개(모델 {config['embed_model']})")
    return done


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------

def parse_extensions(value):
    if not value:
        return set(DEFAULT_EXTENSIONS)
    items = {item.strip().lower() for item in value.split(",") if item.strip()}
    return {item if item.startswith(".") else f".{item}" for item in items}


def split_values(values):
    if values is None:
        return None
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def resolve_folder(text):
    path = Path(text).expanduser().resolve()
    if not path.is_dir():
        raise RagError(f"폴더가 없거나 폴더가 아닙니다: {path}")
    return path


def command_scan(args, config):
    root = resolve_folder(args.path)
    existing = find_collection_for_source(root)
    model = args.model or (collection_model(existing) if existing else config["embed_model"])
    config = bind_model(config, model)
    excludes = split_values(args.exclude) or []
    records, skipped, _ = discover_files(root, parse_extensions(args.ext), excludes)
    chunk_count, total_size = 0, 0
    for record in records.values():
        reason, _ = load_text(root, record)
        if reason:
            extension = Path(record["path"]).suffix.lower()
            skipped[(extension, reason)] = skipped.get((extension, reason), 0) + 1
            continue
        chunk_count += len(document_chunks(record["text"], record["path"]))
        total_size += record["size"]
    readable = sum(1 for record in records.values() if "text" in record)
    print(f"색인 대상: {readable}개 파일, {total_size:,}바이트, 예상 {chunk_count}개 조각")
    print(f"예상 시간: {expected_seconds(config, chunk_count):.1f}초 (모델 {model})")
    if existing:
        print(f"이미 있는 컬렉션: {existing} (같은 폴더라 새로 만들지 않고 갱신합니다)")
    else:
        print(f"제안 이름: {suggest_name(root)}")
    print_skipped(skipped)


def command_index_new(args, config):
    if any((args.file, args.only, args.rebuild, args.prune, args.dry_run)):
        raise RagError("새 폴더 색인에는 --name, --desc, --ext, --exclude, --auto-refresh만 쓸 수 있습니다. 미리 보려면 `rag scan <폴더>`를 실행하세요.")
    source = resolve_folder(args.path)
    existing = find_collection_for_source(source)
    if existing:
        if args.name and args.name != existing:
            print(f"이 폴더는 이미 '{existing}' 컬렉션입니다. 새로 만들지 않고 '{existing}'을 갱신합니다.")
        args.name = existing
        command_index_existing(args, config)
        return
    name = validate_name(args.name or suggest_name(source))
    config = bind_model(config, args.model)
    db_path = INDEX_DIR / f"{name}.db"
    if db_path.exists():
        connection = open_db(db_path)
        old_source = db_metadata(connection).get("source", "")
        connection.close()
        raise RagError(
            f"컬렉션 '{name}'은 이미 다른 폴더({old_source})를 쓰고 있습니다.\n"
            f"- 원본 폴더를 옮긴 것이면: rag move {name} \"{source}\"\n"
            f"- 다른 폴더를 따로 만들려면 다른 이름을 주세요: rag index \"{source}\" --name {suggest_name(source)}"
        )
    connection = create_database(db_path, name, args.desc or "", source, config, args.auto_refresh != "off")
    try:
        extensions = parse_extensions(args.ext)
        excludes = split_values(args.exclude) or []
        update_metadata(connection, "extensions", ",".join(sorted(extensions)))
        update_metadata(connection, "excludes", json.dumps(excludes, ensure_ascii=False))
        print(f"컬렉션 '{name}'을 만듭니다: {source} (모델 {config['embed_model']})")
        run_update(connection, config, name, source, extensions, excludes)
    finally:
        connection.close()


def command_index_existing(args, config):
    path, connection, metadata = get_collection(args.name)
    try:
        target = args.model or metadata.get("model") or config["embed_model"]
        config = bind_model(config, target)
        if args.desc is not None and not args.dry_run:
            update_metadata(connection, "description", args.desc)
        if args.auto_refresh is not None and not args.dry_run:
            update_metadata(connection, "auto_refresh", args.auto_refresh)
        settings_only = (args.desc is not None or args.auto_refresh is not None) and not any(
            (args.file, args.only, args.rebuild, args.prune, args.dry_run, args.ext is not None, args.exclude is not None, args.path,
             args.model))
        if settings_only:
            print("설정을 바꿨습니다.")
            return
        extensions, excludes = collection_settings(metadata)
        if args.ext is not None:
            extensions = parse_extensions(args.ext)
        if args.exclude is not None:
            excludes = split_values(args.exclude)
        if not args.dry_run:
            update_metadata(connection, "extensions", ",".join(sorted(extensions)))
            update_metadata(connection, "excludes", json.dumps(excludes, ensure_ascii=False))
        source = Path(metadata["source"])
        if metadata.get("model") != target:
            print(f"모델을 {metadata.get('model')}에서 {target}(으)로 바꿔 컬렉션 전체를 다시 만듭니다.")
            connection.close()
            connection = None
            rebuild_with_new_model(path, metadata, config, source, extensions, excludes, args)
            return
        run_update(connection, config, args.name, source, extensions, excludes, args.only, split_values(args.file),
                   args.rebuild, args.prune, args.dry_run)
    finally:
        if connection is not None:
            connection.close()


def rebuild_with_new_model(path, metadata, config, source, extensions, excludes, args):
    """모델을 바꿨을 때는 임시 DB에 새로 만든 뒤 바꿔 끼운다. 실패하면 기존 컬렉션이 그대로 남는다."""
    if not source.is_dir():
        raise RagError(f"원본 폴더를 찾을 수 없어 다시 만들 수 없습니다: {source}. 폴더를 옮겼다면 먼저 `rag move`를 실행하세요.")
    if args.file or args.only:
        raise RagError("모델을 바꾼 뒤에는 컬렉션 전체만 다시 만들 수 있습니다. --file, --only 없이 실행하세요.")
    name = metadata["name"]
    temporary = INDEX_DIR / f".{name}-rebuild.db"
    remove_db_files(temporary)
    replacement = create_database(temporary, name, metadata.get("description", ""), source, config,
                                  metadata.get("auto_refresh", "on") == "on")
    try:
        update_metadata(replacement, "extensions", ",".join(sorted(extensions)))
        update_metadata(replacement, "excludes", json.dumps(excludes, ensure_ascii=False))
        run_update(replacement, config, name, source, extensions, excludes, rebuild=True, prune=True, dry_run=args.dry_run)
        replacement.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        replacement.close()
    if args.dry_run:
        remove_db_files(temporary)
        return
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    os.replace(temporary, path)


def command_index(args, config):
    if args.path:
        command_index_new(args, config)
    elif args.name:
        command_index_existing(args, config)
    else:
        raise RagError("rag index에는 <폴더> 또는 --name이 필요합니다.")


def command_move(args, config):
    path, connection, metadata = get_collection(args.name)
    try:
        new_root = resolve_folder(args.path)
        old_root = metadata.get("source", "")
        if path_key(new_root) == path_key(old_root):
            print(f"'{args.name}'은 이미 이 폴더를 쓰고 있습니다: {new_root}")
            return
        other = find_collection_for_source(new_root)
        if other and other != args.name:
            raise RagError(f"이 폴더는 이미 '{other}' 컬렉션의 원본입니다.")
        normalize_stored_paths(connection)
        stored = stored_files(connection)
        extensions, excludes = collection_settings(metadata)
        records, _, _ = discover_files(new_root, extensions, excludes)
        matched, changed, added = [], [], []
        for key, record in sorted(records.items()):
            previous = stored.get(key)
            if previous is None:
                added.append(key)
                continue
            if previous["size"] != record["size"]:
                changed.append(key)
                continue
            reason, _ = load_text(new_root, record)
            if not reason and record["sha256"] == previous["sha256"]:
                matched.append(record)
            else:
                changed.append(key)
        missing = sorted(key for key in stored if key not in records)
        print(f"컬렉션 '{args.name}'의 원본 폴더 바꾸기")
        print(f"- 지금: {old_root}")
        print(f"- 새 폴더: {new_root}")
        print(f"내용이 같은 파일 {len(matched)}개(다시 임베딩하지 않음), 바뀐 파일 {len(changed)}개, "
              f"새 파일 {len(added)}개, 새 폴더에 없는 파일 {len(missing)}개")
        if stored and not matched and not args.force:
            raise RagError("새 폴더에 내용이 같은 파일이 하나도 없습니다. 다른 폴더라면 새 컬렉션으로 만드세요"
                           f"(`rag index \"{new_root}\" --name <새 이름>`). 그래도 바꾸려면 --force를 붙이세요.")
        if not args.yes:
            print(f"아직 바꾸지 않았습니다. 바꾸려면 `rag move {args.name} \"{new_root}\" --yes`를 실행하세요.")
            return
        connection.execute("BEGIN")
        try:
            connection.execute("UPDATE metadata SET value=? WHERE key='source'", (str(new_root),))
            for record in matched:
                connection.execute("UPDATE files SET size=?, mtime_ns=? WHERE path=?",
                                   (record["size"], record["mtime_ns"], record["path"]))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        print(f"원본 폴더를 바꿨습니다. 내용이 같은 파일 {len(matched)}개는 그대로 씁니다.")
        if changed or added or missing:
            print(f"나머지(바뀐 {len(changed)}개, 새 {len(added)}개, 없는 {len(missing)}개)는 "
                  f"`rag index --name {args.name}`으로 갱신하세요. 자동 갱신이 켜져 있으면 다음 검색 때도 반영됩니다.")
    finally:
        connection.close()


def refresh_before_search(connection, metadata, config, name, mode, notices):
    if mode == "no-refresh":
        notices.append(f"[{name}] --no-refresh로 갱신하지 않고 기존 색인으로 검색합니다.")
        return
    if mode == "auto" and metadata.get("auto_refresh", "on") != "on":
        notices.append(f"[{name}] 자동 갱신이 꺼져 있어 기존 색인으로 검색합니다.")
        return
    if joblock.is_running(JOB_DIR, name):
        notices.append(f"[{name}] 지금 이 컬렉션을 색인하는 중이라 지금까지 만든 색인으로 검색합니다. "
                       f"색인이 끝난 뒤 다시 검색하면 나머지 문서에서도 찾습니다.")
        return
    root = Path(metadata.get("source", ""))
    if not root.is_dir():
        notices.append(f"[{name}] 원본 폴더를 찾을 수 없어 기존 색인으로 검색합니다: {root}. "
                       f"폴더를 옮겼다면 `rag move {name} <새 경로>`로 알려 주세요.")
        return
    normalize_stored_paths(connection)
    extensions, excludes = collection_settings(metadata)
    plan = plan_update(connection, root, extensions, excludes)
    if plan.held:
        notices.append(f"[{name}] 색인 파일 중 {plan.held}개(절반 넘게)가 원본에서 사라져 삭제를 보류했습니다. "
                       f"폴더를 옮겼다면 `rag move {name} <새 경로>`를 실행하세요.")
    seconds = expected_seconds(config, plan.chunk_count())
    if seconds > AUTO_REFRESH_LIMIT_SECONDS:
        plan.changes = []
        plan.deletions = []
        apply_plan(connection, config, plan, show_progress=False)
        notices.append(f"[{name}] 바뀐 문서가 많아(갱신 예상 {seconds:.0f}초) 갱신하지 않고 기존 색인으로 검색했습니다. "
                       f"`rag index --name {name}`을 실행한 뒤 다시 검색하면 바뀐 내용으로 찾습니다.")
        return
    done = apply_plan(connection, config, plan, show_progress=False)
    deleted = f", 지운 파일 {len(plan.deletions)}개" if plan.deletions else ""
    notices.append(f"[{name}] 자동 갱신: {done}개 파일{deleted}")


def search_collection(name, question, config, limit, mode, notices):
    _, connection, metadata = get_collection(name)
    try:
        config = bind_model(config, metadata.get("model"))
        refresh_before_search(connection, metadata, config, name, mode, notices)
        vector, dimension = query_vector(config, question)
        if dimension != int(metadata["dimension"]):
            raise RagError("질문 임베딩의 차원이 컬렉션과 다릅니다.")
        rows = connection.execute(
            "SELECT chunks.path, chunks.title, chunks.modified, chunks.body, vec_chunks.distance "
            "FROM vec_chunks JOIN chunks ON chunks.id=vec_chunks.rowid "
            "WHERE vec_chunks.embedding MATCH ? AND k=? ORDER BY vec_chunks.distance",
            (json.dumps(vector), limit),
        ).fetchall()
        source = metadata.get("source", "")
        return [{"similarity": round(1 - row[4], 4), "collection": name, "path": row[0],
                 "file": os.path.join(source, *(find_on_disk(source, row[0]) or row[0]).split("/")),
                 "title": row[1], "modified": row[2],
                 "text": row[3]} for row in rows]
    finally:
        connection.close()


def command_search(args, config):
    if args.all:
        names = [name for name, _, _, _ in list_collections()]
        if not names:
            raise RagError("컬렉션이 없습니다. 먼저 `rag index <폴더>`로 만드세요.")
    else:
        names = [args.name]
    mode = "refresh" if args.refresh else "no-refresh" if args.no_refresh else "auto"
    notices, results = [], []
    for name in names:
        try:
            results.extend(search_collection(name, args.question, config, args.k, mode, notices))
        except RagError as error:
            if not args.all:
                raise
            notices.append(f"[{name}] 이 컬렉션은 건너뛰었습니다: {error}")
    results.sort(key=lambda item: item["similarity"], reverse=True)
    results = results[:args.k]
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    if args.json:
        print(json.dumps({"question": args.question, "notices": notices, "results": results}, ensure_ascii=False, indent=2))
        return
    for notice in notices:
        print(notice)
    if not results:
        print("검색 결과가 없습니다.")
    for item in results:
        print(f"\n[{item['rank']}] 유사도: {item['similarity']:.4f} | 컬렉션: {item['collection']}")
        print(f"파일: {item['path']} | 제목: {item['title'] or '(제목 없음)'} | 문서 수정일: {item['modified']}")
        print(item["text"])


def command_list(args, _config):
    rows = list_collections()
    items = [{
        "name": name,
        "description": metadata.get("description", ""),
        "source": metadata.get("source", ""),
        "source_exists": Path(metadata.get("source", "")).is_dir(),
        "files": files,
        "chunks": chunks,
        "model": metadata.get("model", ""),
        "auto_refresh": metadata.get("auto_refresh", "on"),
        "updated_at": metadata.get("updated_at", ""),
    } for name, metadata, files, chunks in rows]
    if args.json:
        print(json.dumps({"collections": items}, ensure_ascii=False, indent=2))
        return
    if not items:
        print("컬렉션이 없습니다.")
        return
    for item in items:
        missing = "" if item["source_exists"] else " | 원본 폴더 없음(옮겼다면 rag move)"
        print(f"{item['name']} | {item['description']} | {item['source']} | 파일 {item['files']}개 | "
              f"조각 {item['chunks']}개 | {item['model']} | 자동 갱신 {item['auto_refresh']} | "
              f"마지막 갱신 {item['updated_at'] or '없음'}{missing}")


def ollama_model_names(config):
    request = urllib.request.Request(config["ollama_url"].rstrip("/") + "/api/tags")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return {item.get("name", "") for item in json.loads(response.read().decode("utf-8")).get("models", [])}
    except Exception:
        return None


def command_models(args, config):
    if args.add:
        sys.path.insert(0, str(ROOT / "setup"))
        import kit
        return kit.main(["add-model", args.add] + (["--default"] if args.default else []))
    catalog = model_catalog()
    installed = ollama_model_names(config)
    used = {}
    for name, metadata, _, _ in list_collections():
        used.setdefault(metadata.get("model", ""), []).append(name)
    items = []
    for item in catalog.get("models", []):
        items.append({**{key: item.get(key) for key in ("name", "label", "maker", "country", "license", "size_mb", "note")},
                      "default": item["name"] == config["embed_model"],
                      "installed": None if installed is None else item["name"] in installed,
                      "collections": used.get(item["name"], [])})
    if args.json:
        print(json.dumps({"default": config["embed_model"], "models": items}, ensure_ascii=False, indent=2))
        return 0
    if installed is None:
        print("Ollama가 응답하지 않아 받은 모델인지는 확인하지 못했습니다.")
    for item in items:
        state = "받음" if item["installed"] else "안 받음" if item["installed"] is False else "확인 못 함"
        mark = " (기본)" if item["default"] else ""
        users = f" | 쓰는 컬렉션: {', '.join(item['collections'])}" if item["collections"] else ""
        print(f"{item['name']}{mark} | {item['label']} | {item['maker']}({item['country']}) | {item['license']} | "
              f"약 {item['size_mb']}MB | {state}{users}\n    {item['note']}")
    print("\n새 컬렉션은 기본 모델로 만듭니다. 다른 모델로 만들려면 `rag index <폴더> --model <모델>`, "
          "모델을 받으려면 `rag models --add <모델>`(기본으로 바꾸려면 --default)을 실행하세요.")
    return 0


def command_remove(args):
    path = INDEX_DIR / f"{validate_name(args.name)}.db"
    if not path.exists():
        raise RagError(f"컬렉션 '{args.name}'이 없습니다.")
    if not args.yes:
        print(f"지우지 않았습니다. 지울 파일: {path}\n원본 문서는 지우지 않습니다. 지우려면 `rag remove {args.name} --yes`를 실행하세요.")
        return
    remove_db_files(path)
    print(f"컬렉션 '{args.name}'의 DB 파일을 지웠습니다. 원본 문서는 그대로입니다.")


def command_check(_args):
    sys.path.insert(0, str(ROOT / "setup"))
    import kit
    return kit.main(["check"])


def build_parser():
    parser = argparse.ArgumentParser(prog="rag", description="문서 폴더를 로컬 RAG로 만들고 검색합니다.")
    parser.add_argument("--version", action="version", version=f"rag {TOOL_VERSION}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="오류가 나면 추적 정보를 보여 줌")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", parents=[common], help="저장하지 않고 대상 파일과 예상 시간을 보여 줌")
    scan.add_argument("path")
    scan.add_argument("--ext")
    scan.add_argument("--exclude", action="append")
    scan.add_argument("--model")

    index = commands.add_parser("index", parents=[common], help="컬렉션을 만들거나 갱신")
    index.add_argument("path", nargs="?")
    index.add_argument("--name")
    index.add_argument("--desc")
    index.add_argument("--ext")
    index.add_argument("--exclude", action="append")
    index.add_argument("--file", action="append")
    index.add_argument("--only", action="append")
    index.add_argument("--rebuild", action="store_true")
    index.add_argument("--prune", action="store_true")
    index.add_argument("--dry-run", action="store_true")
    index.add_argument("--auto-refresh", choices=("on", "off"))
    index.add_argument("--model", help="임베딩 모델(새 컬렉션, 또는 기존 컬렉션을 다른 모델로 다시 만들 때)")

    search = commands.add_parser("search", parents=[common], help="질문과 가까운 조각 찾기")
    search.add_argument("question")
    target = search.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--all", action="store_true")
    search.add_argument("-k", type=int, default=5)
    refresh = search.add_mutually_exclusive_group()
    refresh.add_argument("--refresh", action="store_true")
    refresh.add_argument("--no-refresh", action="store_true")
    search.add_argument("--json", action="store_true")

    listing = commands.add_parser("list", parents=[common], help="컬렉션 목록")
    listing.add_argument("--json", action="store_true")

    move = commands.add_parser("move", parents=[common], help="원본 폴더를 옮겼을 때 새 경로를 알려 줌")
    move.add_argument("name")
    move.add_argument("path")
    move.add_argument("--yes", action="store_true")
    move.add_argument("--force", action="store_true")

    remove = commands.add_parser("remove", parents=[common], help="컬렉션 지우기(원본 문서는 그대로)")
    remove.add_argument("name")
    remove.add_argument("--yes", action="store_true")

    models = commands.add_parser("models", parents=[common], help="쓸 수 있는 임베딩 모델과 받은 모델")
    models.add_argument("--add", metavar="모델", help="모델을 받는다(반입 파일이 있으면 그것을 씀)")
    models.add_argument("--default", action="store_true", help="--add와 함께 쓰면 기본 모델로 바꾼다")
    models.add_argument("--json", action="store_true")

    commands.add_parser("check", parents=[common], help="이 PC의 설치 상태 점검")
    return parser


def setup_output():
    """Windows에서 출력을 파이프로 받는 프로그램(AI 도구의 터미널 등)은 UTF-8로 읽는다.
    Python 3.14까지는 파이프 출력이 시스템 코드 페이지(한국어 Windows는 CP949)라 글자가 깨지므로 UTF-8로 맞춘다.
    콘솔에 바로 쓸 때는 Windows가 유니코드로 처리하므로 그대로 둔다."""
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


def index_job_key(args):
    """같은 컬렉션의 색인이 겹치지 않게 잠글 이름. 알 수 없으면 None(잠그지 않고 실행해 오류를 그대로 보여 줌)."""
    try:
        if args.path:
            source = resolve_folder(args.path)
            return find_collection_for_source(source) or validate_name(args.name or suggest_name(source))
        return validate_name(args.name) if args.name else None
    except Exception:
        return None


def job_signature(args):
    data = {key: value for key, value in vars(args).items() if key != "debug"}
    if data.get("path"):
        data["path"] = path_key(Path(data["path"]).expanduser().resolve())
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def main(argv=None):
    setup_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "model", None):
        args.model = normalize_model(args.model)
    if getattr(args, "k", 1) < 1:
        parser.error("-k는 1 이상이어야 합니다.")
    if args.command == "index" and not args.dry_run and not os.environ.get("RAG_NO_JOB"):
        key = index_job_key(args)
        if key:
            return joblock.run(JOB_DIR, key, job_signature(args), f"컬렉션 '{key}' 색인", lambda: run_command(args))
    return run_command(args)


def run_command(args):
    try:
        if args.command == "remove":
            command_remove(args)
            return 0
        if args.command == "check":
            return command_check(args)
        config = load_config()
        if args.command == "models":
            return command_models(args, config)
        handlers = {"scan": command_scan, "index": command_index, "search": command_search,
                    "list": command_list, "move": command_move}
        handlers[args.command](args, config)
        return 0
    except KeyboardInterrupt:
        print("\n중단했습니다. 끝난 파일은 저장되어 있으니 같은 명령을 다시 실행하면 이어서 합니다.", file=sys.stderr)
        return 130
    except Exception as error:
        if args.debug:
            raise
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
