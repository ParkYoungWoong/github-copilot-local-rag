"""오래 걸리는 명령(색인, 설치, 반입 준비)을 한 번에 하나만 실행하고, 다시 실행하면 진행 중인 작업에 이어 붙는다.

AI 도구는 오래 걸리는 명령을 기다리다가 먼저 돌아오는 일이 많다. 이때 명령은 꺼지지 않고 뒤에서 계속 돈다.
AI가 같은 명령을 다시 실행해도 작업이 두 번 돌지 않게 하고, 진행 상황과 결과를 이어서 보여 준다.
앞선 작업이 중간에 꺼졌으면(AI 도구를 닫음 등) 다시 실행한 쪽이 이어서 진행한다.

표준 라이브러리만 쓴다(설치 도우미 kit.py와 rag.py가 함께 쓴다).
"""
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import msvcrt
else:
    import fcntl

END_MARK = "[작업 끝]"
HEARTBEAT_SECONDS = 30
TAIL_LINES = 30


def _try_lock(fd):
    try:
        if IS_WINDOWS:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd):
    try:
        if IS_WINDOWS:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _paths(folder, key):
    folder = Path(folder)
    return folder / f"{key}.lock", folder / f"{key}.json", folder / f"{key}.log"


def _read_json(path):
    for _ in range(10):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def _write_json(path, data):
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for _ in range(40):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            # Windows는 다른 프로세스가 읽는 중이면 바꿔 끼우지 못한다. 잠깐 뒤 다시 한다.
            time.sleep(0.05)
    temporary.unlink(missing_ok=True)


def is_running(folder, key):
    """이 key의 작업이 지금 돌고 있는지(잠금을 잡은 프로세스가 있는지)."""
    lock_path = _paths(folder, key)[0]
    if not lock_path.exists():
        return False
    try:
        fd = os.open(lock_path, os.O_RDWR)
    except OSError:
        return False
    try:
        if _try_lock(fd):
            _unlock(fd)
            return False
        return True
    finally:
        os.close(fd)


def duration(seconds):
    seconds = int(max(seconds, 0))
    if seconds < 60:
        return f"{seconds}초"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}분 {seconds}초"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}시간 {minutes}분"


class _Tee:
    """출력을 원래 화면과 작업 기록 파일에 함께 쓴다. 화면 쪽이 닫혀도(AI 도구가 먼저 돌아감) 작업은 계속한다."""

    def __init__(self, stream, log, lock, touch):
        self._stream, self._log, self._lock, self._touch = stream, log, lock, touch

    def write(self, text):
        with self._lock:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
            try:
                self._log.write(text.replace("\r", "\n"))
                self._log.flush()
            except (OSError, ValueError):
                pass
            self._touch()
        return len(text)

    def flush(self):
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except (OSError, ValueError):
            return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _say(text):
    try:
        print(text, flush=True)
    except (OSError, ValueError):
        pass


def _follow(paths, state):
    """잠금이 풀릴 때까지 작업 기록을 이어서 보여 준다. 기록에 끝 표시가 있었는지 돌려준다."""
    lock_path, _, log_path = paths
    started = float(state.get("started") or time.time())
    try:
        data = log_path.read_bytes()
    except OSError:
        data = b""
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) > TAIL_LINES:
        _say(f"  (앞의 {len(lines) - TAIL_LINES}줄은 줄였습니다)")
    for line in lines[-TAIL_LINES:]:
        _say(line)
    ended = any(line.startswith(END_MARK) for line in lines)
    position, pending, quiet_since = len(data), b"", time.time()
    while True:
        finished = not is_running(lock_path.parent, lock_path.stem)
        try:
            with open(log_path, "rb") as file:
                file.seek(position)
                chunk = file.read()
        except OSError:
            chunk = b""
        if chunk:
            position += len(chunk)
            pending += chunk
            *complete, pending = pending.split(b"\n")
            for raw in complete:
                line = raw.decode("utf-8", errors="replace")
                ended = ended or line.startswith(END_MARK)
                _say(line)
            quiet_since = time.time()
        if finished:
            if pending:
                line = pending.decode("utf-8", errors="replace")
                ended = ended or line.startswith(END_MARK)
                _say(line)
            return ended
        if time.time() - quiet_since >= HEARTBEAT_SECONDS:
            _say(f"  ...아직 진행 중입니다(경과 {duration(time.time() - started)})")
            quiet_since = time.time()
        time.sleep(1)


def _hold(paths, signature, title, work):
    _, state_path, log_path = paths
    started = time.time()
    _write_json(state_path, {"pid": os.getpid(), "title": title, "signature": signature,
                             "started": started, "status": "running"})
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    lock = threading.RLock()
    last = [time.time()]
    stop = threading.Event()

    def touch():
        last[0] = time.time()

    originals = sys.stdout, sys.stderr
    sys.stdout = _Tee(originals[0], log, lock, touch)
    sys.stderr = _Tee(originals[1], log, lock, touch)
    hangup = None
    if hasattr(signal, "SIGHUP"):
        try:
            # 터미널이 닫혀도 작업을 끝까지 한다(다시 실행하면 결과를 볼 수 있다).
            hangup = signal.signal(signal.SIGHUP, signal.SIG_IGN)
        except (ValueError, OSError):
            hangup = None

    def heartbeat():
        while not stop.wait(5):
            if time.time() - last[0] >= HEARTBEAT_SECONDS:
                _say(f"  ...아직 진행 중입니다(경과 {duration(time.time() - started)})")

    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()
    code = 1
    try:
        _say(f"[작업 시작] {title}. AI 도구가 기다리다 먼저 돌아와도 같은 명령을 다시 실행하면, "
             "진행 중이면 이어서 보여 주고 멈췄으면 이어서 진행합니다.")
        result = work()
        code = 0 if result is None else int(result)
    except KeyboardInterrupt:
        code = 130
        raise
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
        raise
    except Exception as error:  # 오류도 기록에 남겨야 이어 붙은 쪽이 볼 수 있다.
        _say(f"오류: {error}")
        code = 1
    finally:
        stop.set()
        _say(f"{END_MARK} {title}: " + ("성공" if code == 0 else f"실패(종료 코드 {code})")
             + f", 걸린 시간 {duration(time.time() - started)}")
        _write_json(state_path, {"pid": os.getpid(), "title": title, "signature": signature, "started": started,
                                 "status": "done", "code": code, "ended": time.time()})
        sys.stdout, sys.stderr = originals
        if hangup is not None:
            try:
                signal.signal(signal.SIGHUP, hangup)
            except (ValueError, OSError):
                pass
        log.close()
    return code


def run(folder, key, signature, title, work, reuse_seconds=0, reuse_ok=None):
    """work()를 이 key로 한 번에 하나만 실행하고 종료 코드를 돌려준다.

    - 같은 작업(signature가 같음)이 돌고 있으면 그 작업에 이어 붙어 진행 상황과 결과를 보여 준다.
    - 다른 작업이 돌고 있으면 끝날 때까지 기다렸다가 이 작업을 시작한다.
    - 앞선 작업이 중간에 꺼졌으면 이 작업을 이어서 진행한다(작업은 다시 실행해도 이어서 되게 만들어져 있다).
    - reuse_seconds가 있으면, 같은 작업이 그 시간 안에 성공으로 끝났고 reuse_ok()도 참일 때(그 사이 지우거나 바뀐 것이 없을 때)
      다시 하지 않고 그 결과를 보여 준다.
    """
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return work() or 0
    paths = _paths(folder, key)
    while True:
        try:
            fd = os.open(paths[0], os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return work() or 0  # 잠금 파일을 못 만드는 곳이면 그냥 실행한다.
        if _try_lock(fd):
            try:
                state = _read_json(paths[1]) or {}
                if (reuse_seconds and state.get("status") == "done" and state.get("code") == 0
                        and state.get("signature") == signature
                        and time.time() - float(state.get("ended") or 0) < reuse_seconds
                        and (reuse_ok is None or reuse_ok())):
                    _say(f"같은 작업({state.get('title', title)})이 {duration(time.time() - float(state['ended']))} 전에 "
                         "성공으로 끝났습니다. 다시 하지 않고 그때의 결과를 보여 줍니다.")
                    try:
                        lines = paths[2].read_text(encoding="utf-8", errors="replace").splitlines()
                    except OSError:
                        lines = [f"{END_MARK} {title}: 성공"]
                    for line in lines[-TAIL_LINES:]:
                        _say(line)
                    return 0
                return _hold(paths, signature, title, work)
            finally:
                _unlock(fd)
                os.close(fd)
        os.close(fd)
        state = _read_json(paths[1]) or {}
        same = state.get("signature") == signature
        since = duration(time.time() - float(state.get("started") or time.time()))
        if same:
            _say(f"같은 작업({state.get('title', title)})이 {since} 전부터 진행 중입니다. 새로 시작하지 않고 "
                 "진행 상황과 결과를 이어서 보여 줍니다.")
        else:
            _say(f"다른 작업({state.get('title', '알 수 없음')})이 {since} 전부터 진행 중입니다. "
                 f"끝나면 이어서 이 작업({title})을 시작합니다.")
        ended = _follow(paths, state)
        state = _read_json(paths[1]) or {}
        if same and ended and state.get("status") == "done":
            return int(state.get("code") or 0)
        if not ended:
            _say("앞선 작업이 중간에 멈췄습니다. 이어서 진행합니다.")
