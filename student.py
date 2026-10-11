import atexit
import builtins
import hashlib
import hmac
import io
import json
import keyword
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import traceback
import wave
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any
import bisect, collections, copy, decimal, fractions, functools, heapq, itertools, operator, random, statistics, string  # noqa: F401,E401

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import winsound  
except ImportError:
    winsound = None

BASE = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)  
TASKS_FILE = BASE / "tasks.json"
REPORTS_DIR = BASE / "reports"          
SESSIONS_FILE = BASE / "sessions.json"  
TIME_LIMIT = 3.0          
COMPILE_LIMIT = 20.0      
OUTPUT_LIMIT = 1_000_000  
LANGS = ["Python", "C++", "JavaScript"]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SIGN_KEY = b"olympiad-report-signature-v1-9c41e7"  

TEMPLATES = {
    "Python": "# Ваше решение\nn = int(input())\nprint(n)\n",
    "C++": "#include <iostream>\nusing namespace std;\n\nint main() {\n    \n    return 0;\n}\n",
    "JavaScript": "const lines = require('fs').readFileSync(0, 'utf8').split('\\n');\n\n",
}

UI, MONO = "Segoe UI", "Consolas"
C = dict(
    bg="#0c0e1d", panel="#13162a", card="#1a1e38", card2="#252a50", field="#171b33",
    editor="#0e1020", gutter="#0b0d1a", fg="#e9ebfa", muted="#8b91b8", border="#2b3058",
    accent="#7c5cff", accent2="#22d3ee", ok="#34d399", bad="#fb7185", warn="#fbbf24",
    solved="#0f3b2c", solved2="#17624a", solved_dark="#0b261d",
)



class _Abort(BaseException):
    

    def __init__(self, kind):
        self.kind = kind


def run_python(code, stdin_text, limit=TIME_LIMIT):
    
    lines = iter(stdin_text.split("\n"))
    out, size = [], [0]

    def write(s):
        size[0] += len(s)
        if size[0] > OUTPUT_LIMIT:
            raise _Abort("output")
        out.append(s)

    def fake_input(prompt=""):
        if prompt:
            write(str(prompt))
        try:
            return next(lines)
        except StopIteration:
            raise EOFError("EOF when reading a line")

    def fake_print(*args, sep=" ", end="\n", file=None, flush=False):
        write((" " if sep is None else str(sep)).join(map(str, args)) + ("\n" if end is None else str(end)))

    env = dict(vars(builtins))
    env["input"], env["print"] = fake_input, fake_print
    glob = {"__builtins__": env, "__name__": "__main__"}
    deadline = time.monotonic() + limit

    def tracer(frame, event, arg):
        if time.monotonic() > deadline:
            raise _Abort("timeout")
        return tracer

    status, err = "ok", ""
    try:
        compiled = compile(code, "<student>", "exec")
    except SyntaxError as e:
        return {"status": "error", "out": "", "err": f"SyntaxError (строка {e.lineno}): {e.msg}"}
    try:
        sys.settrace(tracer)
        try:
            exec(compiled, glob)
        finally:
            sys.settrace(None)
    except _Abort as a:
        status = "timeout" if a.kind == "timeout" else "error"
        err = "" if a.kind == "timeout" else "Слишком большой вывод"
    except SystemExit:
        pass
    except BaseException as e:
        status = "error"
        line = ""
        for fr in reversed(traceback.extract_tb(e.__traceback__)):
            if fr.filename == "<student>":
                line = f" (строка {fr.lineno})"
                break
        err = f"{type(e).__name__}{line}: {e}"
    return {"status": status, "out": "".join(out), "err": err}


def _run_process(cmd, stdin_text, cwd):
    if not stdin_text.endswith("\n"):
        stdin_text += "\n"
    try:
        p = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIME_LIMIT, cwd=cwd, creationflags=NOWIN)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "out": "", "err": ""}
    except OSError as e:
        return {"status": "error", "out": "", "err": str(e)}
    out = p.stdout[:OUTPUT_LIMIT]
    if p.returncode != 0:
        return {"status": "error", "out": out, "err": (p.stderr.strip() or f"Код возврата {p.returncode}")[:1500]}
    return {"status": "ok", "out": out, "err": ""}


def compile_cpp(code, tmp):
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        return None, "Компилятор g++/clang++ не найден в PATH."
    src = os.path.join(tmp, "main.cpp")
    exe = os.path.join(tmp, "main.exe" if os.name == "nt" else "main")
    with open(src, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        p = subprocess.run([cxx, "-O2", "-std=c++17", src, "-o", exe], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=COMPILE_LIMIT, cwd=tmp,
                           creationflags=NOWIN)
    except subprocess.TimeoutExpired:
        return None, f"Компиляция заняла больше {int(COMPILE_LIMIT)} с."
    if p.returncode != 0:
        return None, p.stderr.strip()[:3000]
    return exe, ""


def prepare_js(code, tmp):
    node = shutil.which("node")
    if not node:
        return None, "Node.js (node) не найден в PATH."
    src = os.path.join(tmp, "main.js")
    with open(src, "w", encoding="utf-8") as f:
        f.write(code)
    return [node, src], ""


def normalize(s):
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


_PY_STRIP = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|#[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_C_STRIP = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`')


def find_forbidden(code, lang, words):
    
    if not words:
        return []
    names, cleaned = set(), ""
    if lang == "Python":
        try:
            for tok in tokenize.generate_tokens(io.StringIO(code).readline):
                if tok.type == tokenize.NAME:
                    names.add(tok.string)
            cleaned = _PY_STRIP.sub(" ", code)
        except (tokenize.TokenError, SyntaxError, IndentationError):
            cleaned = _PY_STRIP.sub(" ", code)
            names = set(re.findall(r"[A-Za-z_]\w*", cleaned))
    else:
        cleaned = _C_STRIP.sub(" ", code)
        names = set(re.findall(r"[A-Za-z_$][\w$]*", cleaned))
    found = []
    for w in words:
        if re.fullmatch(r"[A-Za-z_$][\w$]*", w):
            if w in names:
                found.append(w)
        elif w in cleaned:
            found.append(w)
    return found



def sign_text(text):
    return hmac.new(SIGN_KEY, text.encode("utf-8"), hashlib.sha256).hexdigest()



def make_wav(path, notes, rate=22050, vol=0.35):
    
    frames = bytearray()
    for freq, ms in notes:
        n = int(rate * ms / 1000)
        for i in range(n):
            if freq <= 0:
                v = 0.0
            else:
                env = min(1.0, i / (rate * 0.008), (n - i) / (rate * 0.04))
                v = vol * env * (math.sin(2 * math.pi * freq * i / rate)
                                 + 0.35 * math.sin(4 * math.pi * freq * i / rate)) / 1.35
            frames += struct.pack("<h", int(v * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


class Sounds:
    SPECS = {
        "ok": [(880, 90), (1175, 150)],
        "fail": [(330, 120), (233, 220)],
        "warn": [(988, 110), (0, 70), (988, 110)],
        "submit": [(523, 110), (659, 110), (784, 110), (1047, 300)],
        "timeup": [(784, 170), (659, 170), (523, 360)],
    }

    def __init__(self, fallback=None):
        self.fallback = fallback
        self.dir = tempfile.mkdtemp(prefix="olymp_snd_")
        atexit.register(shutil.rmtree, self.dir, True)
        self.files = {}
        for name, notes in self.SPECS.items():
            path = os.path.join(self.dir, name + ".wav")
            try:
                make_wav(path, notes)
                self.files[name] = path
            except Exception:
                pass

    def play(self, name):
        path = self.files.get(name)
        try:
            if path and winsound is not None:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            if path and sys.platform == "darwin" and shutil.which("afplay"):
                subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            if path:
                for exe, extra in (("paplay", []), ("aplay", ["-q"]), ("play", ["-q"])):
                    full = shutil.which(exe)
                    if full:
                        subprocess.Popen([full, *extra, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
        except Exception:
            pass
        if self.fallback:
            try:
                self.fallback()
            except Exception:
                pass



def load_tasks():
    if not TASKS_FILE.exists():
        return []
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    tasks = []
    for t in data.get("tasks", [])[:5]:
        tasks.append({
            "title": str(t.get("title", "Без названия")),
            "max_points": int(t.get("max_points", 0)),
            "forbidden": [str(w) for w in t.get("forbidden", [])],
            "tests": [{"input": str(x.get("input", "")), "output": str(x.get("output", ""))}
                      for x in t.get("tests", [])[:20]],
            "image": str(t.get("image", "")),
        })
    return tasks


def load_settings():
    
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return max(0, int(data.get("time_limit_minutes", 0))), str(data.get("submit_dir", "") or "")
    except Exception:
        return 0, ""


def tasks_signature():
    try:
        return hashlib.sha1(TASKS_FILE.read_bytes()).hexdigest()[:12]
    except OSError:
        return "none"


def load_sessions():
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sessions(data):
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, SESSIONS_FILE)
    except OSError:
        pass


def clip(s, n=400):
    s = s if len(s) <= n else s[:n] + "…"
    return s.replace("\n", "\n" + " " * 15)



def mix(a, b, t):
    
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def apply_theme(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=C["bg"])
    s.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["field"],
                bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                troughcolor=C["panel"], font=(UI, 10))
    s.configure("TFrame", background=C["bg"])
    s.configure("TLabel", background=C["bg"], foreground=C["fg"])
    s.configure("TEntry", fieldbackground=C["field"], foreground=C["fg"], insertcolor=C["accent2"],
                padding=8, bordercolor=C["border"])
    s.map("TEntry", bordercolor=[("focus", C["accent"])], lightcolor=[("focus", C["accent"])],
          darkcolor=[("focus", C["accent"])])
    s.configure("TCombobox", fieldbackground=C["card2"], background=C["card2"], foreground=C["fg"],
                arrowcolor=C["accent2"], padding=7, bordercolor=C["border"])
    s.map("TCombobox", fieldbackground=[("readonly", C["card2"])], foreground=[("readonly", C["fg"])],
          selectbackground=[("readonly", C["card2"])], selectforeground=[("readonly", C["fg"])],
          background=[("active", C["accent"])])
    root.option_add("*TCombobox*Listbox.background", C["card2"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    s.configure("Vertical.TScrollbar", background=C["card2"], troughcolor=C["editor"],
                bordercolor=C["editor"], arrowcolor=C["muted"], gripcount=0)
    s.map("Vertical.TScrollbar", background=[("active", C["accent"])])


class GradientLine(tk.Canvas):
    

    def __init__(self, parent, c1=C["accent"], c2=C["accent2"], height=3, bg=None):
        super().__init__(parent, height=height, bg=bg or C["bg"], highlightthickness=0, bd=0)
        self.c1, self.c2, self.line_h = c1, c2, height
        self.bind("<Configure>", self._draw)

    def _draw(self, e):
        self.delete("all")
        n, w = 90, max(e.width, 1)
        for i in range(n):
            self.create_rectangle(w * i / n, 0, w * (i + 1) / n + 1, self.line_h,
                                  fill=mix(self.c1, self.c2, i / (n - 1)), outline="")


class RoundButton(tk.Canvas):
    KINDS = {
        "primary": ("#7c5cff", "#9580ff", "#ffffff"),
        "ghost": ("#262b52", "#333a6c", "#e9ebfa"),
        "success": ("#18a37a", "#22c08f", "#ffffff"),
        "danger": ("#4d2238", "#69304d", "#ffa3b8"),
    }

    def __init__(self, parent, text, command=None, kind="primary", min_text=None, parent_bg=None):
        self._font = tkfont.Font(family=UI, size=10, weight="bold")
        label = max(text, min_text or "", key=len)
        self._bw = self._font.measure(label) + 44
        self._bh = self._font.metrics("linespace") + 20
        super().__init__(parent, width=self._bw, height=self._bh, bg=parent_bg or C["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._command, self._kind = text, command, kind
        self._hover = self._press = self._off = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def _on_press(self, _e):
        self._press = True
        self._draw()

    def _on_release(self, e):
        was = self._press
        self._press = False
        self._draw()
        if was and not self._off and 0 <= e.x <= self._bw and 0 <= e.y <= self._bh and self._command:
            self._command()

    def set_disabled(self, flag):
        self._off = bool(flag)
        self.config(cursor="arrow" if self._off else "hand2")
        self._draw()

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self._draw()

    def _draw(self):
        self.delete("all")
        base, hov, fg = self.KINDS[self._kind]
        if self._off:
            fill, fg = "#191c33", "#5b6190"
        elif self._press:
            fill = mix(base, "#000000", 0.18)
        elif self._hover:
            fill = hov
        else:
            fill = base
        round_rect(self, 1, 1, self._bw - 1, self._bh - 1, 12, fill=fill, outline="")
        self.create_text(self._bw / 2, self._bh / 2, text=self._text, fill=fg, font=self._font)


class TaskChip(tk.Canvas):
    W, H = 188, 54

    def __init__(self, parent, idx, command):
        super().__init__(parent, width=self.W, height=self.H, bg=C["bg"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.idx, self.cmd = idx, command
        self.task_title, self.score, self.maxp = "", 0, 0
        self.solved = self.active = self.off = self.hover = False
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def _hov(self, v):
        self.hover = v
        self.draw()

    def _click(self, _e):
        if not self.off:
            self.cmd(self.idx)

    def set_disabled(self, flag):
        self.off = bool(flag)
        self.config(cursor="arrow" if self.off else "hand2")
        self.draw()

    def refresh_chip(self, title, score, maxp, solved, active):
        self.task_title, self.score, self.maxp = title, score, maxp
        self.solved, self.active = solved, active
        self.draw()

    def draw(self):
        self.delete("all")
        W, H = self.W, self.H
        if self.solved:
            fill, edge = (C["solved2"] if self.active else C["solved"]), C["ok"]
        elif self.active:
            fill, edge = C["card2"], C["accent"]
        else:
            fill, edge = C["card"], C["border"]
        if self.hover and not self.off:
            fill = mix(fill, "#ffffff", 0.07)
        round_rect(self, 2, 2, W - 2, H - 2, 16, fill=fill, outline=edge, width=2)
        cx, cy = 30, H // 2
        self.create_oval(cx - 15, cy - 15, cx + 15, cy + 15, fill=C["ok"] if self.solved else C["panel"],
                         outline=edge, width=2)
        self.create_text(cx, cy, text="✔" if self.solved else str(self.idx + 1),
                         fill="#04281c" if self.solved else C["fg"], font=(UI, 11, "bold"))
        title = self.task_title if len(self.task_title) <= 14 else self.task_title[:13] + "…"
        dim = C["muted"] if (self.off and not self.active) else C["fg"]
        self.create_text(54, cy - 9, text=title, anchor="w", fill=dim, font=(UI, 10, "bold"))
        self.create_text(54, cy + 10, text=f"{self.score} / {self.maxp} баллов", anchor="w",
                         fill=C["muted"], font=(UI, 9))


class TimerPill(tk.Canvas):
    W, H = 176, 48

    def __init__(self, parent):
        super().__init__(parent, width=self.W, height=self.H, bg=C["panel"], highlightthickness=0, bd=0)

    def show(self, text, frac=1.0, color=None):
        self.delete("all")
        if not text:
            return
        W, H = self.W, self.H
        round_rect(self, 1, 1, W - 1, H - 1, 16, fill=C["card"], outline=C["border"])
        self.create_text(W / 2, 20, text=text, fill=color or C["fg"], font=(UI, 14, "bold"))
        x0, x1, y = 18, W - 18, H - 10
        self.create_line(x0, y, x1, y, fill=C["border"], width=4, capstyle="round")
        if frac > 0.02:
            self.create_line(x0, y, x0 + (x1 - x0) * min(frac, 1.0), y, fill=color or C["accent2"],
                             width=4, capstyle="round")


def make_text(parent, **kw):
    frame = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
    txt = tk.Text(frame, bg=C["editor"], fg=C["fg"], insertbackground=C["accent2"], relief="flat",
                  wrap="none", padx=10, pady=8, selectbackground="#3b3f7a", borderwidth=0,
                  highlightthickness=0, **kw)
    sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    return frame, txt



PY_KW = set(keyword.kwlist)
PY_BI = set("print input int str float len range list dict set tuple sum min max abs sorted map enumerate zip bool round open type self".split())
CPP_KW = set("alignas alignof and asm auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not nullptr operator or private protected public register return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while".split())
CPP_BI = set("cin cout cerr endl string vector map set pair queue stack deque min max sort swap size_t printf scanf std".split())
JS_KW = set("async await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof undefined var void while with yield of".split())
JS_BI = set("console require process Math Array Object String Number JSON parseInt parseFloat Map Set".split())

LANG_RULES = {
    "Python": (re.compile(
        r'(?P<com>#[^\n]*)|(?P<str>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')'
        r'|(?P<num>\b\d+(?:\.\d+)?\b)|(?P<word>[A-Za-z_]\w*)'), PY_KW, PY_BI),
    "C++": (re.compile(
        r'(?P<pre>^[ \t]*#[ \t]*\w+)|(?P<com>//[^\n]*|/\*[\s\S]*?\*/)|(?P<str>"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')'
        r'|(?P<num>\b\d+(?:\.\d+)?\b)|(?P<word>[A-Za-z_]\w*)', re.M), CPP_KW, CPP_BI),
    "JavaScript": (re.compile(
        r'(?P<com>//[^\n]*|/\*[\s\S]*?\*/)|(?P<str>"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`)'
        r'|(?P<num>\b\d+(?:\.\d+)?\b)|(?P<word>[A-Za-z_$][\w$]*)'), JS_KW, JS_BI),
}


class CodeEditor(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["border"], padx=1, pady=1)
        font = (MONO, 12)
        self.lang = "Python"
        self._hl_job = None
        self._n = 0
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.gutter = tk.Text(self, width=4, bg=C["gutter"], fg=C["muted"], relief="flat", bd=0, font=font,
                              padx=8, pady=8, state="disabled", takefocus=0, cursor="arrow", wrap="none",
                              highlightthickness=0)
        self.gutter.tag_configure("n", justify="right")
        self.text = tk.Text(self, bg=C["editor"], fg=C["fg"], insertbackground=C["accent2"], relief="flat", bd=0,
                            font=font, wrap="none", padx=10, pady=8, undo=True, selectbackground="#3b3f7a",
                            highlightthickness=0, yscrollcommand=self._on_yscroll)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        self.vsb.grid(row=0, column=2, sticky="ns")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        for tag, color in (("kw", "#b79cff"), ("bi", "#5eead4"), ("str", "#86efac"), ("num", "#fbbf24"),
                           ("pre", "#f9a8d4")):
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("com", foreground="#6b7299", font=(MONO, 12, "italic"))
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.gutter.bind(ev, lambda e: "break")
        self.text.bind("<KeyRelease>", self._changed)
        self.text.bind("<<Paste>>", lambda e: self.after_idle(self._changed))
        self.text.bind("<<Cut>>", lambda e: self.after_idle(self._changed))
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<Tab>", self._on_tab)
        self._refresh_numbers()

    
    def _yview(self, *args):
        self.text.yview(*args)

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        self.gutter.yview_moveto(first)

    def _refresh_numbers(self):
        n = int(self.text.index("end-1c").split(".")[0])
        if n == self._n:
            return
        self._n = n
        self.gutter.config(state="normal")
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)), "n")
        self.gutter.config(state="disabled")
        self.gutter.yview_moveto(self.text.yview()[0])

    def _changed(self, _e=None):
        self._refresh_numbers()
        if self._hl_job:
            self.after_cancel(self._hl_job)
        self._hl_job = self.after(120, self.highlight)

    def highlight(self):
        self._hl_job = None
        rule = LANG_RULES.get(self.lang)
        for tag in ("kw", "bi", "str", "com", "num", "pre"):
            self.text.tag_remove(tag, "1.0", "end")
        if not rule:
            return
        pattern, kws, bis = rule
        code = self.text.get("1.0", "end-1c")
        for m in pattern.finditer(code):
            kind = m.lastgroup
            if kind == "word":
                w = m.group()
                tag = "kw" if w in kws else ("bi" if w in bis else None)
                if tag is None:
                    continue
            else:
                tag = kind
            self.text.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    
    def _on_return(self, _e):
        line = self.text.get("insert linestart", "insert")
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        if line.rstrip().endswith((":", "{")):
            indent += "    "
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        self._changed()
        return "break"

    def _on_tab(self, _e):
        self.text.insert("insert", "    ")
        return "break"

    
    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, code, lang=None, disabled=False):
        if lang:
            self.lang = lang
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", code)
        self.text.edit_reset()
        self._refresh_numbers()
        self.highlight()
        self.set_disabled(disabled)

    def set_disabled(self, flag):
        self.text.config(state="disabled" if flag else "normal")



class StudentApp:
    def __init__(self, root, tasks, minutes=0, submit_dir=""):
        self.root = root
        self.tasks = tasks
        self.minutes = minutes
        self.submit_dir = submit_dir
        root.title("Формативка")
        root.geometry("1440x880")
        root.minsize(1120, 700)
        apply_theme(root)

        self.q = queue.Queue()
        self.sounds = Sounds(fallback=root.bell)
        self.sound_on = True
        self.running = False
        self.started = False       
        self.locked = False        
        self.finalizing = False    
        self.final_wait = False
        self.final_queue = []
        self.final_reason = ""
        self.submitted = False
        self.session_key = ""
        self.deadline = 0.0
        self._warned = set()
        self._built_once = False
        self.cur = 0
        self.img_cache = {}
        self.photo = None
        self._resize_job = None
        self.name_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.state = [{
            "codes": {}, "lang": "Python", "score": 0, "solved": False, "last_run": None,
            "best_code": None, "best_lang": None, "best_passed": 0, "best_total": len(t["tests"]),
        } for t in tasks]

        self._build()
        self._guard_minimize()
        self.select_task(0)
        self._build_start_screen()
        root.protocol("WM_DELETE_WINDOW", self._on_close)  
        self.root.after(40, self._poll)

    
    def _guard_minimize(self):
        self.root.bind("<Unmap>", lambda e: self.root.after(1, self._restore) if e.widget is self.root else None)
        self._watchdog()

    def _restore(self):
        try:
            if self.root.state() == "iconic":
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
        except tk.TclError:
            pass

    def _watchdog(self):
        self._restore()
        self.root.after(200, self._watchdog)

    
    def _build(self):
        r = self.root
        
        top = tk.Frame(r, bg=C["panel"])
        top.pack(fill="x")
        inner = tk.Frame(top, bg=C["panel"])
        inner.pack(fill="x", padx=18, pady=10)
        tk.Label(inner, text="◆", fg=C["accent"], bg=C["panel"], font=(UI, 22, "bold")).pack(side="left")
        tk.Label(inner, text="ФО", fg=C["fg"], bg=C["panel"], font=(UI, 14, "bold")).pack(side="left", padx=(8, 0))
        self.timer = TimerPill(inner)
        self.timer.pack(side="right")
        self.sound_lbl = tk.Label(inner, text="🔊", bg=C["panel"], fg=C["fg"], font=(UI, 15), cursor="hand2")
        self.sound_lbl.pack(side="right", padx=(0, 16))
        self.sound_lbl.bind("<Button-1>", lambda e: self._toggle_sound())
        self.total_lbl = tk.Label(inner, text="", bg=C["panel"], fg=C["fg"], font=(UI, 11, "bold"))
        self.total_lbl.pack(side="right", padx=14)
        self.user_lbl = tk.Label(inner, text="", bg=C["panel"], fg=C["accent2"], font=(UI, 11, "bold"))
        self.user_lbl.pack(side="right", padx=8)
        GradientLine(r, height=3).pack(fill="x")

        
        row = tk.Frame(r, bg=C["bg"])
        row.pack(fill="x", padx=16, pady=(12, 8))
        self.chips = []
        for i in range(len(self.tasks)):
            chip = TaskChip(row, i, self.select_task)
            chip.pack(side="left", padx=(0, 8))
            self.chips.append(chip)

        
        self.header = tk.Frame(r, bg=C["card"])
        self.header.pack(fill="x", padx=16, pady=(0, 8))
        self.h_stripe = tk.Frame(self.header, bg=C["accent"], width=6)
        self.h_stripe.pack(side="left", fill="y")
        self.h_title = tk.Label(self.header, bg=C["card"], fg=C["fg"], font=(UI, 14, "bold"))
        self.h_title.pack(side="left", padx=(14, 8), pady=12)
        self.h_meta = tk.Label(self.header, bg=C["card"], fg=C["muted"], font=(UI, 10))
        self.h_meta.pack(side="left", padx=6)
        self.h_chip = tk.Label(self.header, bg=C["card"], fg=C["accent2"], font=(UI, 11, "bold"))
        self.h_chip.pack(side="right", padx=16)
        self.header_kids = [self.h_title, self.h_meta, self.h_chip]

        
        foot = tk.Frame(r, bg=C["panel"])
        foot.pack(side="bottom", fill="x")
        fin = tk.Frame(foot, bg=C["panel"])
        fin.pack(fill="x", padx=18, pady=10)
        self.sign_lbl = tk.Label(fin, text="✍  Подпись: —", bg=C["panel"], fg=C["muted"], font=(UI, 10))
        self.sign_lbl.pack(side="left")
        self.submit_btn = RoundButton(fin, "✅  Сдать работу", self.submit_clicked, kind="success", parent_bg=C["panel"])
        self.submit_btn.pack(side="right")
        RoundButton(fin, "💾  Копия отчёта", self.save_report, kind="ghost", parent_bg=C["panel"]).pack(side="right", padx=10)

        
        main = ttk.PanedWindow(r, orient="horizontal")
        main.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.left = tk.Frame(main, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        self.left_caption = tk.Label(self.left, text="УСЛОВИЕ ЗАДАЧИ", bg=C["card"], fg=C["muted"], font=(UI, 9, "bold"))
        self.left_caption.pack(anchor="w", padx=14, pady=(10, 0))
        self.img_label = tk.Label(self.left, bg=C["card"], fg=C["muted"], text="")
        self.img_label.pack(fill="both", expand=True, padx=6, pady=6)
        self.left.bind("<Configure>", self._on_left_resize)
        main.add(self.left, weight=3)

        right = ttk.Frame(main)
        main.add(right, weight=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=2)

        tool = tk.Frame(right, bg=C["bg"])
        tool.grid(row=0, column=0, sticky="ew", pady=(0, 8), padx=(8, 0))
        tk.Label(tool, text="Язык", bg=C["bg"], fg=C["muted"], font=(UI, 10, "bold")).pack(side="left")
        self.lang_var = tk.StringVar(value="Python")
        self.lang_cb = ttk.Combobox(tool, textvariable=self.lang_var, values=LANGS, state="readonly", width=14)
        self.lang_cb.pack(side="left", padx=10)
        self.lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)
        self.run_btn = RoundButton(tool, "▶  Запустить тесты", self.run_tests, kind="primary",
                                   min_text="⏳  Выполняется…", parent_bg=C["bg"])
        self.run_btn.pack(side="right")

        self.code = CodeEditor(right)
        self.code.grid(row=1, column=0, sticky="nsew", padx=(8, 0))
        r.bind("<Control-Return>", lambda e: self.run_tests())
        r.bind("<F5>", lambda e: self.run_tests())

        tk.Label(right, text="КОНСОЛЬ РЕЗУЛЬТАТОВ", bg=C["bg"], fg=C["muted"], font=(UI, 9, "bold")).grid(
            row=2, column=0, sticky="w", pady=(12, 4), padx=(8, 0))
        cf, self.console = make_text(right, font=(MONO, 11), state="disabled", height=8)
        cf.grid(row=3, column=0, sticky="nsew", padx=(8, 0))
        self.console.tag_configure("ok", foreground="#6ee7b7", background="#11352a", spacing1=3, spacing3=3, lmargin1=8)
        self.console.tag_configure("bad", foreground="#fda4af", background="#3a1a2a", spacing1=3, spacing3=1, lmargin1=8)
        self.console.tag_configure("detail", foreground="#e5d0d8", background="#2a1824", lmargin1=26, lmargin2=26)
        self.console.tag_configure("info", foreground=C["muted"], spacing1=4)
        self.console.tag_configure("head", foreground=C["accent2"], font=(MONO, 11, "bold"), spacing1=4)

    
    def _build_start_screen(self):
        ov = tk.Frame(self.root, bg=C["bg"])
        ov.place(x=0, y=0, relwidth=1, relheight=1)
        bg = tk.Canvas(ov, bg=C["bg"], highlightthickness=0, bd=0)
        bg.place(x=0, y=0, relwidth=1, relheight=1)
        bg.bind("<Configure>", lambda e: self._draw_backdrop(bg, e.width, e.height))
        box = tk.Frame(ov, bg=C["card"], padx=48, pady=34, highlightthickness=1, highlightbackground=C["border"])
        box.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(box, text="◆", bg=C["card"], fg=C["accent"], font=(UI, 34, "bold")).pack()
        tk.Label(box, text="Формативная оценка", bg=C["card"], fg=C["fg"], font=(UI, 26, "bold")).pack()
        tk.Label(box, text="по информатике", bg=C["card"], fg=C["muted"], font=(UI, 12)).pack(pady=(0, 14))
        pills = tk.Frame(box, bg=C["card"])
        pills.pack(pady=(0, 18))
        time_info = f"  ⏱ Общий лимит: {self.minutes} мин  " if self.minutes else "  время не ограничено  "
        info = [f"  {len(self.tasks)} задач  ", time_info]
        for text in info:
            tk.Label(pills, text=text, bg=C["card2"], fg=C["accent2"], font=(UI, 10, "bold"), pady=5).pack(side="left", padx=4)

        lbl = dict(bg=C["card"], fg=C["muted"], font=(UI, 10, "bold"), anchor="w")
        tk.Label(box, text="ФИО", **lbl).pack(fill="x")
        e1 = ttk.Entry(box, textvariable=self.name_var, width=40, font=(UI, 12))
        e1.pack(fill="x", pady=(4, 12))
        tk.Label(box, text="ГРУППА", **lbl).pack(fill="x")
        e2 = ttk.Entry(box, textvariable=self.group_var, width=40, font=(UI, 12))
        e2.pack(fill="x", pady=(4, 14))
        if self.minutes:
            warn = ("Таймер запустится после нажатия «Начать».\n"
                    "Когда время выйдет, работа сдастся автоматически.")
        else:
            warn = "Когда закончите, нажмите «Сдать работу»."
        tk.Label(box, text=warn, bg=C["card"], fg=C["muted"], font=(UI, 10), justify="left").pack(anchor="w", pady=(0, 14))
        RoundButton(box, "Начать →", self.start, kind="primary", min_text="Начать →      ",
                    parent_bg=C["card"]).pack()
        e1.bind("<Return>", lambda e: e2.focus_set())
        e2.bind("<Return>", lambda e: self.start())
        e1.focus_set()
        self.start_overlay = ov

    @staticmethod
    def _draw_backdrop(cv, w, h):
        cv.delete("all")
        for fx, fy, rad, col, k in ((0.10, 0.18, 280, C["accent"], 0.12), (0.90, 0.80, 340, C["accent2"], 0.08),
                                    (0.78, 0.12, 170, C["accent"], 0.07), (0.20, 0.88, 200, C["accent2"], 0.06)):
            cv.create_oval(fx * w - rad, fy * h - rad, fx * w + rad, fy * h + rad, fill=mix(C["bg"], col, k), outline="")

    def start(self):
        name, group = self.name_var.get().strip(), self.group_var.get().strip()
        if not name or not group:
            messagebox.showwarning("Начало", "Введите ФИО и группу.")
            return
        key = f"{tasks_signature()}|{name.casefold()}|{group.casefold()}"
        sessions = load_sessions()
        sess = sessions.get(key)
        elapsed = 0.0
        if isinstance(sess, dict):
            if sess.get("submitted"):
                messagebox.showinfo("Работа уже сдана", "Работа этого ученика уже сдана.\n" + str(sess.get("report", "")))
                return
            try:
                elapsed = max(0.0, time.time() - float(sess.get("start", time.time())))
            except (TypeError, ValueError):
                elapsed = 0.0
            self._restore_state(sess.get("state"))
        else:
            sessions[key] = {"start": time.time(), "submitted": False}
            save_sessions(sessions)
        self.session_key = key
        self.started = True
        self.user_lbl.config(text=f"👤 {name} · {group}")
        self.sign_lbl.config(text=f"✍  Работа подписана: {name} · {group}", fg=C["fg"])
        self.start_overlay.destroy()
        self.select_task(0, commit=False)
        if self.minutes:
            self.deadline = time.monotonic() + self.minutes * 60 - elapsed
        self._tick()
        self._autosave()

    _STATE_KEYS = ("codes", "lang", "score", "solved", "last_run", "best_code", "best_lang", "best_passed", "best_total")

    def _restore_state(self, saved):
        if not isinstance(saved, list) or len(saved) != len(self.state):
            return
        for st, sv in zip(self.state, saved):
            if not isinstance(sv, dict):
                continue
            for k in self._STATE_KEYS:
                if k in sv and k != "last_run":
                    st[k] = sv[k]
            lr = sv.get("last_run")
            st["last_run"] = tuple(lr) if isinstance(lr, list) and len(lr) == 2 else None
            if st["lang"] not in LANGS or not isinstance(st["codes"], dict):
                st["lang"], st["codes"] = "Python", {}

    def _persist(self, submitted=False, report=""):
        if not self.session_key:
            return
        try:
            self._commit_editor()
        except tk.TclError:
            pass
        sessions = load_sessions()
        sess = sessions.get(self.session_key)
        if not isinstance(sess, dict):
            sess = {"start": time.time(), "submitted": False}
        sess["state"] = [{k: st.get(k) for k in self._STATE_KEYS} for st in self.state]
        if submitted:
            sess["submitted"] = True
            sess["report"] = report
        sessions[self.session_key] = sess
        save_sessions(sessions)

    def _autosave(self):
        if self.started and not self.submitted:
            self._persist()
        self.root.after(20000, self._autosave)

    def _on_close(self):
        try:
            if self.started and not self.submitted:
                self._persist()
        finally:
            self.root.destroy()

    
    def _sound(self, name, always=False):
        if always or self.sound_on:
            self.sounds.play(name)

    def _toggle_sound(self):
        self.sound_on = not self.sound_on
        self.sound_lbl.config(text="🔊" if self.sound_on else "🔇")
        if self.sound_on:
            self.sounds.play("ok")

    
    def _tick(self):
        if self.submitted or self.finalizing:
            return
        if not self.minutes:
            self.timer.show("без лимита", 1.0, C["accent2"])
            return

        rem = self.deadline - time.monotonic()
        if rem <= 0:
            self.timer.show("00:00", 0.0, C["bad"])
            self._sound("timeup", always=True)
            self._begin_finalize("время вышло")
            return

        total_s = self.minutes * 60
        left = int(rem) + 1
        for mark in (300, 60):
            if left <= mark < total_s and mark not in self._warned:
                self._warned.add(mark)
                self._sound("warn")
        m, sec = divmod(left, 60)
        h, m = divmod(m, 60)
        text = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
        color = C["bad"] if left <= 300 else (C["warn"] if left <= 600 else C["accent2"])
        self.timer.show("⏱ " + text, rem / total_s, color)
        self.root.after(500, self._tick)

    
    def _commit_editor(self):
        st = self.state[self.cur]
        st["codes"][st["lang"]] = self.code.get()

    def select_task(self, i, commit=True):
        if self.running:
            return
        if commit and self._built_once:
            self._commit_editor()
        self._built_once = True
        self.cur = i
        st = self.state[i]
        self.lang_var.set(st["lang"])
        self._load_editor(st["lang"])
        self._set_console_text([("Нажмите «Запустить тесты» (Ctrl+Enter).", "info")])
        self._refresh_header()
        self._refresh_chips()
        self._show_image()

    def _load_editor(self, lang):
        st = self.state[self.cur]
        self.code.set(st["codes"].get(lang, TEMPLATES[lang]), lang=lang, disabled=self.locked)

    def _on_lang_change(self, _e):
        if self.running or self.locked:
            self.lang_var.set(self.state[self.cur]["lang"])
            return
        self._commit_editor()
        st = self.state[self.cur]
        st["lang"] = self.lang_var.get()
        self._load_editor(st["lang"])

    def _refresh_header(self):
        t, st = self.tasks[self.cur], self.state[self.cur]
        solved = st["solved"]
        bg = C["solved"] if solved else C["card"]
        self.header.config(bg=bg)
        for w in self.header_kids:
            w.config(bg=bg)
        self.h_stripe.config(bg=C["ok"] if solved else C["accent"])
        self.h_title.config(text=f"Задача {self.cur + 1} · {t['title']}", fg="#ffffff" if solved else C["fg"])
        forb = ", ".join(t["forbidden"]) if t["forbidden"] else "нет"
        self.h_meta.config(text=(f"{t['max_points']} баллов   ·   тестов: {len(t['tests'])}   "
                                 f"·   запрещено: {forb}"),
                           fg="#bdeedc" if solved else C["muted"])
        self.h_chip.config(text="✔  РЕШЕНО" if solved else f"{st['score']} / {t['max_points']} баллов",
                           fg="#ffffff" if solved else C["accent2"])
        side = C["solved_dark"] if solved else C["card"]
        self.left.config(bg=side, highlightbackground=C["ok"] if solved else C["border"],
                         highlightthickness=4 if solved else 1)
        self.left_caption.config(bg=side, fg="#7ee2b8" if solved else C["muted"])
        self.img_label.config(bg=side)

    def _refresh_chips(self):
        total = sum(s["score"] for s in self.state)
        maxp = sum(t["max_points"] for t in self.tasks)
        self.total_lbl.config(text=f"Итого: {total} / {maxp}")
        for i, chip in enumerate(self.chips):
            st, t = self.state[i], self.tasks[i]
            chip.refresh_chip(t["title"], st["score"], t["max_points"], st["solved"], i == self.cur)

    def _apply_controls(self):
        off = self.running or self.locked
        self.run_btn.set_disabled(off)
        self.run_btn.set_text("⏳  Выполняется…" if self.running else "▶  Запустить тесты")
        self.lang_cb.config(state="disabled" if off else "readonly")
        for chip in self.chips:
            chip.set_disabled(off)

    
    def _get_image(self):
        if self.cur in self.img_cache:
            return self.img_cache[self.cur]
        path = BASE / self.tasks[self.cur]["image"]
        img = None
        try:
            img = Image.open(path).convert("RGB") if HAS_PIL else tk.PhotoImage(file=str(path))
        except Exception:
            img = None
        self.img_cache[self.cur] = img
        return img

    def _on_left_resize(self, _e):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._show_image)

    def _show_image(self):
        self._resize_job = None
        img: Any = self._get_image()
        if img is None:
            self.img_label.config(image="", text="Не удалось загрузить фото условия", fg=C["bad"])
            return
        w = max(self.left.winfo_width() - 20, 50)
        h = max(self.left.winfo_height() - 50, 50)
        if w < 60 or h < 60:
            return
        if HAS_PIL:
            scale = min(w / img.width, h / img.height, 2.0)
            size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            self.photo = ImageTk.PhotoImage(img.resize(size, Image.Resampling.LANCZOS))
        else:
            k = max(1, -(-img.width() // w), -(-img.height() // h))
            self.photo = img.subsample(k, k)
        self.img_label.config(image=self.photo, text="")

    
    def _set_console_text(self, items):
        self.console.config(state="normal")
        self.console.delete("1.0", "end")
        self.console.config(state="disabled")
        for text, tag in items:
            self._console_line(text, tag)

    def _console_line(self, text, tag):
        self.console.config(state="normal")
        self.console.insert("end", text + "\n", tag)
        self.console.config(state="disabled")
        self.console.see("end")

    
    def run_tests(self, forced=False):
        if self.running or not self.started or self.submitted or (self.locked and not forced):
            return
        self._commit_editor()
        st, t = self.state[self.cur], self.tasks[self.cur]
        lang, code = st["lang"], st["codes"].get(st["lang"], "")
        self._set_console_text([])
        if not code.strip():
            self._console_line("Редактор пуст.", "bad")
            return
        bad = find_forbidden(code, lang, t["forbidden"])
        if bad:
            self._console_line("⛔ Использованы запрещённые команды: " + ", ".join(bad), "bad")
            self._console_line("Тесты не запускались. Перепишите решение без них.", "info")
            if not self.finalizing:
                self._sound("fail")
            return
        self._set_running(True)
        self._console_line(f"Запуск ({lang}), тестов: {len(t['tests'])}…", "head")
        threading.Thread(target=self._worker, args=(self.cur, lang, code, t["tests"]), daemon=True).start()

    def _set_running(self, flag):
        self.running = flag
        self._apply_controls()

    def _worker(self, idx, lang, code, tests):
        put = self.q.put
        passed, scored, tmp = 0, True, None
        try:
            if lang == "Python":
                runner = lambda inp: run_python(code, inp)
            else:
                tmp = tempfile.mkdtemp(prefix="olymp_")
                if lang == "C++":
                    exe, err = compile_cpp(code, tmp)
                    cmd = [exe] if exe else None
                else:
                    cmd, err = prepare_js(code, tmp)
                if cmd is None:
                    put(("line", ("Ошибка компиляции:\n" if lang == "C++" else "Ошибка: ") + err, "bad"))
                    scored = False
                    return
                runner = lambda inp: _run_process(cmd, inp, tmp)

            for n, tc in enumerate(tests, 1):
                res = runner(tc["input"])
                expected = normalize(tc["output"])
                got = normalize(res["out"])
                if res["status"] == "ok" and got == expected:
                    passed += 1
                    put(("line", f"✔ Тест {n}: пройден", "ok"))
                    continue
                reason = {"timeout": f"превышено время ({int(TIME_LIMIT)} с)",
                          "error": "ошибка выполнения"}.get(res["status"], "неверный ответ")
                put(("line", f"✘ Тест {n}: {reason}", "bad"))
                put(("line", f"Ввод:       {clip(tc['input'] or '(пусто)')}", "detail"))
                put(("line", f"Ожидалось:  {clip(expected)}", "detail"))
                put(("line", f"Получено:   {clip(got or '(пусто)')}", "detail"))
                if res["err"]:
                    put(("line", f"Ошибка:     {clip(res['err'], 600)}", "detail"))
        except Exception as e:
            put(("line", f"Внутренняя ошибка проверки: {e}", "bad"))
            scored = False
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            put(("done", idx, lang, code, passed, len(tests), scored))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                try:
                    if msg[0] == "line":
                        self._console_line(msg[1], msg[2])
                    elif msg[0] == "done":
                        self._finish(*msg[1:])
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def _finish(self, idx, lang, code, passed, total, scored):
        self._set_running(False)
        t, st = self.tasks[idx], self.state[idx]
        st["last_run"] = (lang, code)
        if scored:
            score = t["max_points"] if passed == total else int(t["max_points"] * passed / total + 0.5)
            if score >= st["score"]:
                st.update(score=score, best_code=code, best_lang=lang, best_passed=passed, best_total=total)
            if passed == total:
                st["solved"] = True
            ok = passed == total
            self._console_line(f"{'🎉' if ok else '•'} Пройдено {passed} из {total} · баллы за запуск: {score}/{t['max_points']}",
                               "ok" if ok else "info")
            self._refresh_header()
            self._refresh_chips()
            if not self.finalizing:
                self._sound("ok" if ok else "fail")
        self._persist()
        if self.finalizing:
            if self.final_wait:
                self.final_wait = False
                self._plan_final()
            else:
                self._next_final()

    # ---------- сдача работы ----------
    def submit_clicked(self):
        if not self.started or self.submitted or self.finalizing:
            return
        if messagebox.askyesno("Сдать работу", "После сдачи изменить решения будет нельзя.\nСдать работу сейчас?"):
            self._begin_finalize("сдано учеником")

    def _lock_ui(self):
        self.locked = True
        self.code.set_disabled(True)
        self.submit_btn.set_disabled(True)
        self._apply_controls()

    def _needs_run(self, i):
        st = self.state[i]
        lang = st["lang"]
        code = st["codes"].get(lang, "")
        if not code.strip() or code == TEMPLATES[lang]:
            return False
        return not (st["last_run"] and tuple(st["last_run"]) == (lang, code))

    def _begin_finalize(self, reason):
        if not self.started or self.finalizing or self.submitted:
            return
        self.finalizing = True
        self.final_reason = reason
        self._lock_ui()
        if self.running:
            self.final_wait = True  
        else:
            self._plan_final()

    def _plan_final(self):
        self._commit_editor()
        self.final_queue = [i for i in range(len(self.tasks)) if self._needs_run(i)]
        self._next_final()

    def _next_final(self):
        while self.final_queue:
            i = self.final_queue.pop(0)
            self.select_task(i)
            self.run_tests(forced=True)
            if self.running:
                return           
        self._write_submission()

    def _write_submission(self):
        self._commit_editor()
        name = self.name_var.get().strip() or "Без имени"
        group = self.group_var.get().strip() or "-"
        text = self.build_report(name, group, f"Причина сдачи: {self.final_reason}")
        safe = lambda v: re.sub(r"[^\w\-]+", "_", v, flags=re.U).strip("_") or "x"
        path = REPORTS_DIR / f"report_{safe(group)}_{safe(name)}_{datetime.now():%Y%m%d_%H%M%S}.txt"
        try:
            REPORTS_DIR.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            self.finalizing = False
            self.submit_btn.set_disabled(False)
            messagebox.showerror("Не удалось сохранить отчёт", f"{e}\n\nНажмите «Сдать работу» ещё раз.")
            return
        sent, send_err = "", ""
        if self.submit_dir:
            try:
                dst = Path(self.submit_dir)
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst / path.name)
                sent = str(dst / path.name)
            except OSError as e:
                send_err = str(e)
        self.submitted = True
        self.finalizing = False
        self._persist(submitted=True, report=str(path))
        total = sum(st["score"] for st in self.state)
        auto = "время" in self.final_reason
        self.timer.show("✔ Сдано", 1.0, C["ok"])
        self._sound("submit", always=True)
        self._console_line(f"Работа сдана и подписана: {name} · {group}", "ok")
        self._console_line(f"Отчёт: {path}", "info")
        if sent:
            self._console_line(f"Отправлено учителю: {sent}", "info")
        if send_err:
            self._console_line(f"Не удалось отправить в папку учителя: {send_err}", "bad")
        head = "Время вышло — работа сдана автоматически." if auto else "Работа сдана."
        body = f"{head}\n\nПодпись: {name} · {group}\nИтого баллов: {total}\n\nОтчёт сохранён:\n{path}"
        if sent:
            body += f"\n\nОтправлено учителю:\n{sent}"
        if send_err:
            body += f"\n\nВНИМАНИЕ: в папку учителя отправить не удалось ({send_err}).\nПокажите файл отчёта учителю."
        self.root.after(50, lambda: messagebox.showinfo("Работа сдана", body))

    
    def build_report(self, name, group, note=""):
        now = datetime.now()
        total = sum(s["score"] for s in self.state)
        maxp = sum(t["max_points"] for t in self.tasks)
        L = ["ОТЧЁТ УЧЕНИКА", "=" * 64, f"ФИО:    {name}", f"Группа: {group}", f"Дата:   {now:%d.%m.%Y %H:%M:%S}"]
        if note:
            L.append(note)
        time_limit = f"{self.minutes} мин" if self.minutes else "нет"
        L += [f"Общий лимит времени: {time_limit}", f"ИТОГО БАЛЛОВ: {total} из {maxp}", ""]
        for i, (t, st) in enumerate(zip(self.tasks, self.state), 1):
            if st["best_code"] is not None:
                code, lang = st["best_code"], st["best_lang"]
                tests = f"{st['best_passed']}/{st['best_total']}"
            else:
                lang = st["lang"]
                code = st["codes"].get(lang, "")
                tests = "0 (тесты не пройдены или не запускались)"
                if not code.strip() or code == TEMPLATES[lang]:
                    code = "(решение не написано)"
            L += ["=" * 64, f"Задача {i}: {t['title']}", f"Автор: {name} · {group}",
                  f"Баллы: {st['score']} / {t['max_points']}",
                  f"Пройдено тестов: {tests}", f"Язык: {lang}",
                  "-" * 64, code.rstrip(), ""]
        signed = ("\n".join(L) + "\n" + "=" * 64 + "\n"
                  + f"ПОДПИСЬ: {name} · {group} · {now:%d.%m.%Y %H:%M:%S}\n")
        return signed + "КОНТРОЛЬНАЯ СУММА: " + sign_text(signed) + "\n"

    def save_report(self):
        if self.running or not self.started:
            return
        self._commit_editor()
        name, group = self.name_var.get().strip(), self.group_var.get().strip()
        safe = re.sub(r"[^\w\-]+", "_", name, flags=re.U).strip("_") or "report"
        path = filedialog.asksaveasfilename(title="Сохранить копию отчёта", defaultextension=".txt",
                                            initialfile=f"report_{safe}.txt", filetypes=[("Текстовый файл", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text(self.build_report(name, group), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Ошибка записи", str(e))
            return
        messagebox.showinfo("Отчёт", f"Отчёт сохранён:\n{path}")


def main():
    root = tk.Tk()
    tasks = load_tasks()
    if not tasks:
        messagebox.showerror("Нет задач", f"Не найден или пуст файл:\n{TASKS_FILE}\n\nСначала создайте задачи в teacher.py.")
        root.destroy()
        return
    minutes, submit_dir = load_settings()
    StudentApp(root, tasks, minutes, submit_dir)
    root.mainloop()


if __name__ == "__main__":
    main()