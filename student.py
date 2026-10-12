import builtins
import hashlib
import io
import json
import keyword
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import traceback
import exporter
from typing import Any
import bisect, collections, copy, decimal, fractions, functools, heapq, itertools, math, operator, random, statistics, string  
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)  
TASKS_FILE = BASE / "tasks.json"
REPORTS_DIR = BASE / "reports"        
SESSIONS_FILE = BASE / "sessions.json"  
MAX_TASKS = 10
TIME_LIMIT = 3.0          
COMPILE_LIMIT = 20.0      
OUTPUT_LIMIT = 1_000_000  
LANGS = ["Python", "C++", "JavaScript"]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PYTHON_KEYWORDS = set(keyword.kwlist) | {"False", "None", "True"}
PYTHON_BUILTINS = set(dir(builtins)) - {"__build_class__", "__debug__"}
CPP_KEYWORDS = set("""
alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept auto
bitand bitor bool break case catch char char8_t char16_t char32_t class compl
concept const consteval constexpr constinit const_cast continue co_await co_return
co_yield decltype default delete do double dynamic_cast else enum explicit export
extern false float for friend goto if inline int long mutable namespace new noexcept
not not_eq nullptr operator or or_eq private protected public reflexpr register
reinterpret_cast requires return short signed sizeof static static_assert static_cast
struct switch synchronized template this thread_local throw true try typedef typeid
typename union unsigned using virtual void volatile wchar_t while xor xor_eq
""".split())
JAVASCRIPT_KEYWORDS = set("""
as async await break case catch class const continue debugger default delete do else
export extends false finally for from function get if import in instanceof let new
null of return set static super switch this throw true try typeof var void while with
yield undefined
""".split())
_PYTHON_TOKEN_RE = re.compile(
    r"(?P<comment>\#[^\n]*)|"
    r"(?P<string>\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|"
    r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|"
    r"(?P<decorator>^[ \t]*@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)|"
    r"(?P<number>\b(?:0[xX][\da-fA-F]+|0[bB][01]+|0[oO][0-7]+|"
    r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?j?))|"
    r"(?P<identifier>[A-Za-z_]\w*)|"
    r"(?P<operator>\*\*=?|//=?|<<=?|>>=?|:=|==|!=|<=|>=|->|"
    r"[+\-*/%@&|^~<>=!]=?|[()[\]{}.,:;])",
    re.MULTILINE,
)
_C_TOKEN_RE = re.compile(
    r"(?P<preprocessor>^[ \t]*\#[^\n]*)|"
    r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|"
    r"(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|"
    r"(?P<number>\b(?:0[xX][\da-fA-F]+|0[bB][01]+|"
    r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[uUlLfF]*))|"
    r"(?P<identifier>[A-Za-z_$][\w$]*)|"
    r"(?P<operator>\+\+|--|->|::|&&|\|\||==|!=|<=|>=|"
    r"\+=|-=|\*=|/=|%=|<<=?|>>=?|[+\-*/%&|^~<>=!?:;.,()[\]{}])",
    re.MULTILINE,
)
_JS_TOKEN_RE = re.compile(
    r"(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|"
    r"(?P<string>`(?:\\.|[^`\\])*`|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|"
    r"(?P<number>\b(?:0[xX][\da-fA-F]+|0[bB][01]+|0[oO][0-7]+|"
    r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?n?))|"
    r"(?P<identifier>[A-Za-z_$][\w$]*)|"
    r"(?P<operator>\+\+|--|=>|===?|!==?|<=|>=|&&|\|\||\?\?|"
    r"\?\.|\*\*=?|[+\-*/%&|^~<>=!?:;.,()[\]{}])",
    re.MULTILINE,
)

TEMPLATES = {
    "Python": "# Ваше решение\nn = int(input())\nprint(n)\n",
    "C++": "#include <iostream>\nusing namespace std;\n\nint main() {\n    \n    return 0;\n}\n",
    "JavaScript": "const lines = require('fs').readFileSync(0, 'utf8').split('\\n');\n\n",
}

C = dict(
    bg="#0c0e1d", panel="#13162a", field="#171b33", editor="#0e1020",
    fg="#e9ebfa", muted="#8b91b8", border="#2b3058", accent="#7c5cff",
    ok="#34d399", bad="#fb7185", solved="#0f3b2c", solved_dark="#0b261d",
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
        import sys
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



def apply_theme(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=C["bg"])
    s.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["field"],
                bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                troughcolor=C["panel"], font=("Segoe UI", 10))
    s.configure("TFrame", background=C["bg"])
    s.configure("Panel.TFrame", background=C["panel"])
    s.configure("TLabel", background=C["bg"], foreground=C["fg"])
    s.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
    s.configure("TEntry", fieldbackground=C["field"], foreground=C["fg"], insertcolor=C["fg"],
                padding=7, bordercolor=C["border"])
    s.configure("TButton", background=C["field"], foreground=C["fg"], padding=(14, 8),
                borderwidth=0, focusthickness=0, focuscolor=C["field"])
    s.map("TButton", background=[("active", "#3a3f55"), ("disabled", "#23252f")],
          foreground=[("disabled", C["muted"])])
    s.configure("Accent.TButton", background=C["accent"], foreground="#ffffff",
                font=("Segoe UI", 10, "bold"))
    s.map("Accent.TButton", background=[("active", "#8aa3ff"), ("disabled", "#3b4468")])

    s.configure("Task.TButton", background=C["field"], padding=(16, 8))
    s.configure("TaskActive.TButton", background="#252a50", foreground="#ffffff")
    s.configure("TaskDone.TButton", background="#17624a", foreground="#ffffff")
    s.configure("TaskDoneActive.TButton", background=C["ok"], foreground="#07150f")
    s.map("Task.TButton", background=[("active", "#3a3f55")])
    s.map("TaskActive.TButton", background=[("active", "#343b67")])
    s.map("TaskDone.TButton", background=[("active", "#20845f")])
    s.map("TaskDoneActive.TButton", background=[("active", "#48e0a2")])
    s.configure("TCombobox", fieldbackground=C["field"], background=C["field"], foreground=C["fg"],
                arrowcolor=C["fg"], padding=6, bordercolor=C["border"])
    s.map("TCombobox", fieldbackground=[("readonly", C["field"])], foreground=[("readonly", C["fg"])],
          selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["fg"])])
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    s.configure("Vertical.TScrollbar", background=C["field"], troughcolor=C["panel"],
                bordercolor=C["panel"], arrowcolor=C["muted"])


def make_text(parent, **kw):
    frame = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
    txt = tk.Text(frame, bg=C["editor"], fg=C["fg"], insertbackground=C["fg"], relief="flat",
                  wrap="none", padx=10, pady=8, selectbackground="#3b4a85", **kw)
    sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    return frame, txt


def load_tasks():
    if not TASKS_FILE.exists():
        return []
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    tasks = []
    for t in data.get("tasks", [])[:MAX_TASKS]:
        tasks.append({
            "title": str(t.get("title", "Без названия")),
            "max_points": int(t.get("max_points", 0)),
            "forbidden": [str(w) for w in t.get("forbidden", [])],
            "tests": [{"input": str(x.get("input", "")), "output": str(x.get("output", ""))}
                      for x in t.get("tests", [])[:20]],
            "image": str(t.get("image", "")),
        })
    return tasks


def load_time_limit():
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return max(0, int(data.get("time_limit_minutes", 0)))
    except Exception:
        return 0


def load_submit_dir():
    if not TASKS_FILE.exists():
        return ""
    data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    return str(data.get("submit_dir", "") or "").strip()


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



class StudentApp:
    def __init__(self, root, tasks, minutes=0):
        self.root = root
        self.tasks = tasks
        self.minutes = minutes
        root.title("Формативная оценка-рабочее место ученика")
        root.geometry("1440x860")
        root.minsize(1100, 680)
        apply_theme(root)

        self.q = queue.Queue()
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
        self._highlight_job = None
        self.editor_font_size = 12
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
        
        bar = ttk.Frame(r)
        bar.pack(fill="x", padx=16, pady=(12, 6))
        ttk.Label(bar, text="Формативная оценка", font=("Segoe UI", 15, "bold")).pack(side="left", padx=(0, 18))
        self.task_btns = []
        for i in range(len(self.tasks)):
            b = ttk.Button(bar, command=lambda i=i: self.select_task(i))
            b.pack(side="left", padx=3)
            self.task_btns.append(b)
        self.timer_lbl = ttk.Label(bar, text="", font=("Segoe UI", 14, "bold"))
        self.timer_lbl.pack(side="right", padx=(18, 0))
        self.total_lbl = ttk.Label(bar, text="", font=("Segoe UI", 11, "bold"))
        self.total_lbl.pack(side="right")

        
        self.header = tk.Frame(r, bg=C["panel"])
        self.header.pack(fill="x", padx=16, pady=(0, 8))
        self.h_title = tk.Label(self.header, bg=C["panel"], fg=C["fg"], font=("Segoe UI", 13, "bold"))
        self.h_title.pack(side="left", padx=14, pady=10)
        self.h_info = tk.Label(self.header, bg=C["panel"], fg=C["muted"], font=("Segoe UI", 10))
        self.h_info.pack(side="left", padx=6)
        self.h_chip = tk.Label(self.header, bg=C["panel"], fg=C["ok"], font=("Segoe UI", 10, "bold"))
        self.h_chip.pack(side="right", padx=14)
        self.header_kids = [self.h_title, self.h_info, self.h_chip]

        
        main = ttk.PanedWindow(r, orient="horizontal")
        main.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.left = tk.Frame(main, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        self.img_label = tk.Label(self.left, bg=C["panel"], fg=C["muted"], text="")
        self.img_label.pack(fill="both", expand=True, padx=6, pady=6)
        self.left.bind("<Configure>", self._on_left_resize)
        main.add(self.left, weight=3)

        right = ttk.Frame(main)
        main.add(right, weight=2)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=2)

        tool = ttk.Frame(right)
        tool.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(tool, text="Язык:").pack(side="left")
        self.lang_var = tk.StringVar(value="Python")
        self.lang_cb = ttk.Combobox(tool, textvariable=self.lang_var, values=LANGS, state="readonly", width=14)
        self.lang_cb.pack(side="left", padx=8)
        self.lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)
        self.submit_btn = ttk.Button(tool, text="✓  Сдать работу", style="Accent.TButton",
                                     command=self.submit_clicked)
        self.submit_btn.pack(side="right", padx=(8, 0))
        self.run_btn = ttk.Button(tool, text="▶  Запустить тесты", style="Accent.TButton", command=self.run_tests)
        self.run_btn.pack(side="right")

        self.editor_font = tkfont.Font(root=r, family="Consolas", size=self.editor_font_size)
        self.editor_comment_font = tkfont.Font(
            root=r, family="Consolas", size=self.editor_font_size, slant="italic")
        ef, self.editor = make_text(right, font=self.editor_font, undo=True)
        ef.grid(row=1, column=0, sticky="nsew")
        syntax_colors = {
            "syntax_keyword": "#c792ea",
            "syntax_builtin": "#82aaff",
            "syntax_function": "#82aaff",
            "syntax_class": "#ffcb6b",
            "syntax_string": "#c3e88d",
            "syntax_number": "#f78c6c",
            "syntax_comment": "#697098",
            "syntax_operator": "#89ddff",
            "syntax_decorator": "#f07178",
            "syntax_preprocessor": "#f07178",
        }
        for tag, color in syntax_colors.items():
            self.editor.tag_configure(tag, foreground=color,
                                      font=self.editor_comment_font if tag == "syntax_comment"
                                      else self.editor_font)
        self.editor.bind("<<Modified>>", self._on_editor_modified)
        self.editor.bind("<Control-MouseWheel>", self._zoom_editor)
        self.editor.bind("<Control-Button-4>", self._zoom_editor)
        self.editor.bind("<Control-Button-5>", self._zoom_editor)
        self.editor.bind("<Return>", self._on_return)
        self.editor.bind("<Tab>", lambda e: (self.editor.insert("insert", "    "), "break")[1])
        r.bind("<Control-Return>", lambda e: self.run_tests())
        r.bind("<F5>", lambda e: self.run_tests())

        ttk.Label(right, text="Консоль результатов", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 4))
        cf, self.console = make_text(right, font=("Consolas", 11), state="disabled", height=8)
        cf.grid(row=3, column=0, sticky="nsew")
        self.console.tag_configure("ok", foreground=C["ok"])
        self.console.tag_configure("bad", foreground=C["bad"])
        self.console.tag_configure("detail", foreground=C["fg"])
        self.console.tag_configure("info", foreground=C["muted"], spacing1=4)
        self.console.tag_configure("head", foreground=C["accent"], font=("Consolas", 11, "bold"), spacing1=4)

        
        foot = ttk.Frame(r)
        foot.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Label(foot, text="ФИО:").pack(side="left")
        self.name_entry = ttk.Entry(foot, textvariable=self.name_var, width=34)
        self.name_entry.pack(side="left", padx=(8, 18))
        ttk.Label(foot, text="Группа:").pack(side="left")
        self.group_entry = ttk.Entry(foot, textvariable=self.group_var, width=12)
        self.group_entry.pack(side="left", padx=(8, 18))

    
    def _commit_editor(self):
        st = self.state[self.cur]
        st["codes"][st["lang"]] = self.editor.get("1.0", "end-1c")

    def _zoom_editor(self, event):
        if getattr(event, "num", None) in (4, 5):
            direction = 1 if event.num == 4 else -1
        else:
            direction = 1 if event.delta > 0 else -1 if event.delta < 0 else 0
        new_size = max(8, min(32, self.editor_font_size + direction))
        if new_size != self.editor_font_size:
            self.editor_font_size = new_size
            self.editor_font.configure(size=new_size)
            self.editor_comment_font.configure(size=new_size)
        return "break"

    def _on_editor_modified(self, _event=None):
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        if self._highlight_job is not None:
            self.root.after_cancel(self._highlight_job)
        self._highlight_job = self.root.after(80, self._highlight_editor)

    def _highlight_editor(self):
        self._highlight_job = None
        syntax_tags = (
            "syntax_keyword", "syntax_builtin", "syntax_function", "syntax_class",
            "syntax_string", "syntax_number", "syntax_comment", "syntax_operator",
            "syntax_decorator", "syntax_preprocessor",
        )
        for tag in syntax_tags:
            self.editor.tag_remove(tag, "1.0", "end")
        lang = self.lang_var.get()
        if lang == "Python":
            token_re, keywords = _PYTHON_TOKEN_RE, PYTHON_KEYWORDS
        elif lang == "C++":
            token_re, keywords = _C_TOKEN_RE, CPP_KEYWORDS
        else:
            token_re, keywords = _JS_TOKEN_RE, JAVASCRIPT_KEYWORDS
        expect_name = None
        code = self.editor.get("1.0", "end-1c")
        try:
            for token in token_re.finditer(code):
                kind = token.lastgroup
                value = token.group()
                tag = None
                if kind == "identifier":
                    if expect_name:
                        tag, expect_name = f"syntax_{expect_name}", None
                    elif value in keywords:
                        tag = "syntax_keyword"
                        if lang == "Python" and value in {"class", "def"}:
                            expect_name = "class" if value == "class" else "function"
                        elif lang != "Python" and value in {"class", "struct", "interface"}:
                            expect_name = "class"
                        elif lang != "Python" and value in {"function", "func"}:
                            expect_name = "function"
                    elif lang == "Python" and value in PYTHON_BUILTINS:
                        tag = "syntax_builtin"
                    elif value in {"True", "False", "None", "true", "false", "null", "undefined"}:
                        tag = "syntax_builtin"
                    elif value[:1].isupper():
                        tag = "syntax_class"
                    elif code[token.end():].lstrip().startswith("("):
                        tag = "syntax_function"
                else:
                    expect_name = None
                if kind == "comment":
                    tag = "syntax_comment"
                elif kind == "string":
                    tag = "syntax_string"
                elif kind == "number":
                    tag = "syntax_number"
                elif kind == "operator":
                    tag = "syntax_operator"
                elif kind == "decorator":
                    tag = "syntax_decorator"
                elif kind == "preprocessor":
                    tag = "syntax_preprocessor"
                if tag:
                    start = self.editor.index(f"1.0+{token.start()}c")
                    end = self.editor.index(f"1.0+{token.end()}c")
                    self.editor.tag_add(tag, start, end)
        except tk.TclError:
            return

    def select_task(self, i, commit=True):
        if self.running:
            return
        if commit and hasattr(self, "_built_once"):
            self._commit_editor()
        self._built_once = True
        self.cur = i
        st = self.state[i]
        self.lang_var.set(st["lang"])
        self._load_editor(st["lang"])
        self._set_console_text([("Нажмите «Запустить тесты» (Ctrl+Enter).", "info")])
        self._refresh_header()
        self._refresh_buttons()
        self._show_image()

    def _load_editor(self, lang):
        st = self.state[self.cur]
        self.editor.config(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", st["codes"].get(lang, TEMPLATES[lang]))
        self.editor.edit_reset()
        self.editor.config(state="disabled" if self.locked else "normal")
        self.editor.edit_modified(False)
        if self._highlight_job is not None:
            self.root.after_cancel(self._highlight_job)
            self._highlight_job = None
        self._highlight_editor()

    def _on_lang_change(self, _e):
        if self.running:
            self.lang_var.set(self.state[self.cur]["lang"])
            return
        self._commit_editor()
        st = self.state[self.cur]
        st["lang"] = self.lang_var.get()
        self._load_editor(st["lang"])

    def _refresh_header(self):
        t, st = self.tasks[self.cur], self.state[self.cur]
        solved = st["solved"]
        bg = C["solved"] if solved else C["panel"]
        self.header.config(bg=bg)
        for w in self.header_kids:
            w.config(bg=bg)
        self.h_title.config(text=f"Задача {self.cur + 1}. {t['title']}", fg=C["fg"])
        forb = ", ".join(t["forbidden"]) if t["forbidden"] else "нет"
        self.h_info.config(text=f"·  {t['max_points']} баллов  ·  тестов: {len(t['tests'])}  ·  запрещено: {forb}",
                           fg=C["muted"])
        self.h_chip.config(text="✔ ЗАДАЧА РЕШЕНА" if solved else f"Баллы: {st['score']}/{t['max_points']}",
                           fg=C["ok"] if solved else C["muted"])
        self.left.config(bg=C["solved_dark"] if solved else C["panel"],
                         highlightbackground=C["ok"] if solved else C["border"],
                         highlightthickness=4 if solved else 1)
        self.img_label.config(bg=C["solved_dark"] if solved else C["panel"])

    def _refresh_buttons(self):
        total = sum(s["score"] for s in self.state)
        maxp = sum(t["max_points"] for t in self.tasks)
        self.total_lbl.config(text=f"Итого: {total} / {maxp}")
        for i, b in enumerate(self.task_btns):
            st, t = self.state[i], self.tasks[i]
            active = i == self.cur
            style = ("TaskDoneActive" if active else "TaskDone") if st["solved"] else ("TaskActive" if active else "Task")
            b.config(style=f"{style}.TButton", text=f"{i + 1}. {t['title'][:18]}  ({st['score']}/{t['max_points']})")

    
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
        h = max(self.left.winfo_height() - 20, 50)
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

    
    def _on_return(self, _e):
        line = self.editor.get("insert linestart", "insert")
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        if line.rstrip().endswith((":", "{")):
            indent += "    "
        self.editor.insert("insert", "\n" + indent)
        self.editor.see("insert")
        return "break"

    
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
            self._console_line("⛔ Использованы запрещённые слова: " + ", ".join(bad), "bad")
            self._console_line("Тесты не запускались. Перепишите решение без них.", "info")
            return
        self._set_running(True)
        self._console_line(f"Запуск ({lang}), тестов: {len(t['tests'])}…", "head")
        threading.Thread(target=self._worker, args=(self.cur, lang, code, t["tests"]), daemon=True).start()

    def _set_running(self, flag):
        self.running = flag
        off = flag or self.locked
        self.run_btn.config(state="disabled" if off else "normal",
                            text="⏳  Выполняется…" if flag else "▶  Запустить тесты")
        self.lang_cb.config(state="disabled" if off else "readonly")
        for b in self.task_btns:
            b.state(["disabled"] if off else ["!disabled"])

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
            self._refresh_buttons()
        self._persist()
        if self.finalizing:
            if self.final_wait:
                self.final_wait = False
                if self.final_reason == "сдано учеником":
                    self._write_submission()
                else:
                    self._plan_final()
            else:
                self._next_final()

    
    def _build_start_screen(self):
        ov = tk.Frame(self.root, bg=C["bg"])
        ov.place(x=0, y=0, relwidth=1, relheight=1)
        box = tk.Frame(ov, bg=C["panel"], padx=44, pady=34)
        box.place(relx=0.5, rely=0.45, anchor="center")
        lbl = dict(bg=C["panel"], fg=C["fg"], font=("Segoe UI", 11), anchor="w")
        tk.Label(box, text="Формативная оценка", bg=C["panel"], fg=C["fg"],
                 font=("Segoe UI", 20, "bold")).grid(row=0, column=0, pady=(0, 6))
        if self.minutes:
            info = f"Задач: {len(self.tasks)}  ·  время: {self.minutes} мин"
            warn = "Таймер запустится после нажатия «Начать».\nКогда время выйдет, работа сдастся автоматически."
        else:
            info = f"Задач: {len(self.tasks)}  ·  время не ограничено"
            warn = "Когда закончите, нажмите «Сдать работу»."
        tk.Label(box, text=info, bg=C["panel"], fg=C["muted"], font=("Segoe UI", 11)).grid(row=1, column=0)
        tk.Label(box, text="ФИО", **lbl).grid(row=2, column=0, sticky="w", pady=(22, 4))
        e1 = ttk.Entry(box, textvariable=self.name_var, width=38)
        e1.grid(row=3, column=0, sticky="ew")
        tk.Label(box, text="Группа", **lbl).grid(row=4, column=0, sticky="w", pady=(12, 4))
        e2 = ttk.Entry(box, textvariable=self.group_var, width=38)
        e2.grid(row=5, column=0, sticky="ew")
        tk.Label(box, text=warn, bg=C["panel"], fg=C["muted"], font=("Segoe UI", 10), justify="left").grid(
            row=6, column=0, sticky="w", pady=(16, 14))
        ttk.Button(box, text="Начать", style="Accent.TButton", command=self.start).grid(row=7, column=0, sticky="ew")
        e1.bind("<Return>", lambda e: e2.focus_set())
        e2.bind("<Return>", lambda e: self.start())
        e1.focus_set()
        self.start_overlay = ov

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
        self.name_entry.state(["disabled"])
        self.group_entry.state(["disabled"])
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

    def _tick(self):
        if self.submitted or self.finalizing:
            return
        rem = self.deadline - time.monotonic()
        if rem <= 0:
            self.timer_lbl.config(text="⏱ 00:00 · автопроверка…", foreground=C["bad"])
            self._begin_finalize("время вышло")
            return
        left = int(rem) + 1
        m, sec = divmod(left, 60)
        h, m = divmod(m, 60)
        text = f"⏱ {h}:{m:02d}:{sec:02d}" if h else f"⏱ {m:02d}:{sec:02d}"
        self.timer_lbl.config(text=text, foreground=C["bad"] if left <= 300 else C["fg"])
        self.root.after(500, self._tick)

    
    def submit_clicked(self):
        if not self.started or self.submitted or self.finalizing:
            return
        self._begin_finalize("сдано учеником")

    def _lock_ui(self):
        self.locked = True
        self.editor.config(state="disabled")
        self.run_btn.config(state="disabled")
        self.lang_cb.config(state="disabled")
        self.submit_btn.state(["disabled"])
        for b in self.task_btns:
            b.state(["disabled"])

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
        elif reason == "сдано учеником":
            self._write_submission()
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
        items = []
        for task, st in zip(self.tasks, self.state):
            lang = st["lang"]
            code = st["codes"].get(lang, "")
            is_tested_version = lang == st["best_lang"] and code == st["best_code"]
            passed = st["best_passed"] if is_tested_version else 0
            total = st["best_total"] if is_tested_version else len(task["tests"])
            solved = bool(st["solved"] and is_tested_version and total > 0 and passed == total)
            image = Path(task["image"]) if task["image"] else None
            if image and not image.is_absolute():
                image = BASE / image
            items.append({
                "title": task["title"],
                "lang": lang,
                "code": code,
                "solved": solved,
                "score": st["score"] if is_tested_version else 0,
                "max_points": task["max_points"],
                "passed": passed,
                "total": total,
                "image": str(image) if image else "",
            })
        safe = exporter.safe_name
        base = f"{safe(group)}_{safe(name)}_{datetime.now():%Y%m%d_%H%M%S_%f}"
        submit_dir = load_submit_dir()
        folder = Path(submit_dir).expanduser() if submit_dir else REPORTS_DIR
        try:
            result = exporter.save_submission(folder, base, name, group, items, self.final_reason)
            if not result["png"]:
                detail = "\n".join(result["errors"]) or "Изображение не создано."
                raise RuntimeError(detail)
            if not result["json"]:
                raise RuntimeError("Не удалось сохранить данные для сводки.")
        except (OSError, RuntimeError, ValueError) as e:
            self.finalizing = False
            self.submit_btn.state(["!disabled"])
            messagebox.showerror("Не удалось сохранить работу", f"{e}\n\nНажмите «Сдать работу» ещё раз.")
            return
        self.submitted = True
        self.finalizing = False
        self._persist(submitted=True, report=str(result["png"]))
        total = sum(item["score"] for item in items)
        auto = "время" in self.final_reason
        self.timer_lbl.config(text="✔ Сдано", foreground=C["ok"])
        self._console_line(f"Работа сдана. Изображение: {result['png']}", "ok")
        msg = ("Время вышло — работа сдана автоматически." if auto else "Работа сдана.")
        if result.get("csv"):
            details = f"Сводки обновлены:\n{result['csv'][0]}\n{result['csv'][1]}"
            show_message = messagebox.showinfo
        else:
            details = "CSV не обновлены:\n" + "\n".join(result["errors"])
            show_message = messagebox.showwarning
        self.root.after(50, lambda: show_message(
            "Работа сдана", f"{msg}\nИтого баллов: {total}\n\nИзображение:\n{result['png']}\n\n{details}"))

def main():
    root = tk.Tk()
    tasks = load_tasks()
    if not tasks:
        messagebox.showerror("Нет задач", f"Не найден или пуст файл:\n{TASKS_FILE}\n\nСначала создайте задачи в teacher.py.")
        root.destroy()
        return
    StudentApp(root, tasks, load_time_limit())
    root.mainloop()


if __name__ == "__main__":
    main()