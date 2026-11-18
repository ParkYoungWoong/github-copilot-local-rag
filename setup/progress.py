"""오래 걸리는 일(설치, 반입 준비)의 진행 상황을 터미널과 브라우저 화면에 함께 보여 준다.

AI 도구는 명령 출력을 끝난 뒤에 한꺼번에 보여 주기도 해서, 사용자가 지금 무엇을 하는지 알 수 있게
진행 상황 화면(progress.html)을 따로 만들어 브라우저로 연다. 화면은 2초마다 스스로 새로 고친다.
"""
import html
import os
import sys
import time
import webbrowser
from pathlib import Path


class Progress:
    def __init__(self, title, steps, page=None, open_browser=False):
        self.title = title
        self.steps = list(steps)
        self.states = ["대기"] * len(self.steps)
        self.details = [""] * len(self.steps)
        self.current = -1
        self.fraction = 0.0
        self.page = Path(page) if page else None
        self.started = time.time()
        self.finished = None
        self.message = ""
        self.interactive = sys.stdout.isatty()
        self.shown = -1
        self.written = 0.0
        if self.page:
            self.write(force=True)
            if open_browser:
                try:
                    webbrowser.open(self.page.resolve().as_uri())
                except Exception:
                    pass

    # 단계 -----------------------------------------------------------------

    def start(self, index, label=None):
        if 0 <= self.current < len(self.steps) and self.states[self.current] == "진행 중":
            self.states[self.current] = "완료"
        self.current = index
        if label:
            self.steps[index] = label
        self.states[index] = "진행 중"
        self.fraction = 0.0
        self.shown = -1
        print(f"[{index + 1}/{len(self.steps)}] {self.steps[index]}", flush=True)
        self.write(force=True)

    def note(self, text):
        print(f"  {text}", flush=True)
        if self.current >= 0:
            self.details[self.current] = text
        self.write()

    def update(self, done, total, text=""):
        """단계 안의 진행률. 터미널이면 한 줄을 덮어쓰고, 아니면 10% 단위로 줄을 남긴다."""
        self.fraction = max(0.0, min(1.0, done / total)) if total else 0.0
        percent = int(self.fraction * 100)
        bar = "#" * (percent // 5) + "-" * (20 - percent // 5)
        line = f"  [{bar}] {percent:3d}% {text}".rstrip()
        if self.interactive:
            print("\r" + line, end="" if percent < 100 else "\n", flush=True)
        elif percent // 10 != self.shown:
            self.shown = percent // 10
            print(line, flush=True)
        if self.current >= 0 and text:
            self.details[self.current] = f"{percent}% {text}"
        self.write()

    def finish_step(self, text=""):
        if self.current >= 0:
            self.states[self.current] = "완료"
            if text:
                self.details[self.current] = text
        self.fraction = 0.0
        self.write(force=True)

    def close(self, ok, message=""):
        if 0 <= self.current < len(self.steps) and self.states[self.current] == "진행 중":
            self.states[self.current] = "완료" if ok else "실패"
        self.finished = "완료" if ok else "실패"
        self.message = message
        self.write(force=True)

    # 화면 -----------------------------------------------------------------

    def overall(self):
        done = sum(1 for state in self.states if state == "완료")
        if self.finished == "완료":
            return 100
        return int((done + (self.fraction if self.current >= 0 and self.states[self.current] == "진행 중" else 0))
                   * 100 / max(len(self.steps), 1))

    def write(self, force=False):
        if not self.page or (not force and time.time() - self.written < 0.7):
            return
        self.written = time.time()
        elapsed = int(time.time() - self.started)
        refresh = "" if self.finished else '<meta http-equiv="refresh" content="2">'
        rows = []
        for number, (label, state, detail) in enumerate(zip(self.steps, self.states, self.details), 1):
            rows.append(f'<li class="{ {"완료": "done", "진행 중": "now", "실패": "fail"}.get(state, "wait") }">'
                        f'<span class="state">{html.escape(state)}</span>'
                        f'<span class="label">{number}. {html.escape(label)}</span>'
                        f'<span class="detail">{html.escape(detail)}</span></li>')
        if self.finished:
            status = f"{self.finished}: {html.escape(self.message)}" if self.message else self.finished
        else:
            status = "진행 중입니다. 이 화면은 저절로 새로 고쳐집니다. 창을 닫아도 작업은 계속됩니다."
        body = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">{refresh}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(self.title)}</title>
<style>
  :root {{ color-scheme: light dark; --bg: #f6f7f9; --card: #fff; --text: #1d2330; --muted: #677085; --line: #e3e6ec;
          --accent: #2f6fde; --done: #1f8a4c; --fail: #c4372d; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #15171c; --card: #1f222a; --text: #e8eaf0; --muted: #9aa2b4;
          --line: #2e323c; --accent: #6b9cff; --done: #4cc184; --fail: #ff7a6e; }} }}
  body {{ margin: 0; padding: 32px 16px; background: var(--bg); color: var(--text);
          font: 15px/1.6 -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; background: var(--card); border: 1px solid var(--line);
          border-radius: 12px; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 16px; }}
  .bar {{ height: 12px; background: var(--line); border-radius: 6px; overflow: hidden; }}
  .bar > div {{ height: 100%; width: {self.overall()}%; background: var(--accent); transition: width .3s; }}
  .percent {{ font-size: 28px; font-weight: 700; margin: 12px 0 4px; }}
  ul {{ list-style: none; padding: 0; margin: 20px 0 0; }}
  li {{ display: grid; grid-template-columns: 64px 1fr; gap: 2px 12px; padding: 10px 0; border-top: 1px solid var(--line); }}
  .state {{ font-size: 12px; font-weight: 700; color: var(--muted); padding-top: 2px; }}
  .detail {{ grid-column: 2; color: var(--muted); font-size: 13px; word-break: break-all; }}
  li.done .state {{ color: var(--done); }} li.now .state {{ color: var(--accent); }} li.fail .state {{ color: var(--fail); }}
  li.now .label {{ font-weight: 700; }}
  .status {{ margin-top: 16px; color: var(--muted); font-size: 13px; }}
</style></head>
<body><main>
<h1>{html.escape(self.title)}</h1>
<div class="meta">시작한 지 {elapsed // 60}분 {elapsed % 60}초</div>
<div class="percent">{self.overall()}%</div>
<div class="bar"><div></div></div>
<ul>{''.join(rows)}</ul>
<p class="status">{status}</p>
</main></body></html>
"""
        temporary = self.page.with_name(self.page.name + ".tmp")
        try:
            temporary.write_text(body, encoding="utf-8")
            os.replace(temporary, self.page)
        except OSError:
            pass


class Quiet:
    """진행 상황 화면 없이 쓸 때(점검, 시험)의 같은 모양 객체."""

    def start(self, index, label=None):
        pass

    def note(self, text):
        print(f"  {text}", flush=True)

    def update(self, done, total, text=""):
        pass

    def finish_step(self, text=""):
        pass

    def close(self, ok, message=""):
        pass
