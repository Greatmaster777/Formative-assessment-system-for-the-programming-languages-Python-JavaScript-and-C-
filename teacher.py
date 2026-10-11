import json
import os
import re
import sys
import shutil
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import exporter  

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:  
    HAS_PIL = False

BASE = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)  
TASKS_FILE = BASE / "tasks.json"
IMG_DIR = BASE / "images"
MAX_TASKS = 5
MAX_TESTS = 20

C = dict(
    bg="#16171d", panel="#1f212b", field="#2a2d3a", fg="#e6e8ee", muted="#8b90a0",
    accent="#6c8cff", ok="#3fb97f", bad="#ef5b6b", border="#383c4e", editor="#1a1b22",
)



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
    s.configure("Panel.TLabel", background=C["panel"], foreground=C["fg"])
    s.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
    s.configure("Title.TLabel", background=C["bg"], foreground=C["fg"], font=("Segoe UI", 16, "bold"))
    s.configure("TEntry", fieldbackground=C["field"], foreground=C["fg"], insertcolor=C["fg"],
                padding=7, bordercolor=C["border"])
    s.configure("TButton", background=C["field"], foreground=C["fg"], padding=(14, 8),
                borderwidth=0, focusthickness=0, focuscolor=C["field"])
    s.map("TButton", background=[("active", "#3a3f55"), ("disabled", "#23252f")],
          foreground=[("disabled", C["muted"])])
    s.configure("Accent.TButton", background=C["accent"], foreground="#ffffff", font=("Segoe UI", 10, "bold"))
    s.map("Accent.TButton", background=[("active", "#8aa3ff"), ("disabled", "#3b4468")])
    s.configure("Danger.TButton", background="#4a2830", foreground="#ff9aa6")
    s.map("Danger.TButton", background=[("active", "#63323c")])
    s.configure("Vertical.TScrollbar", background=C["field"], troughcolor=C["panel"],
                bordercolor=C["panel"], arrowcolor=C["muted"])


def make_text(parent, height=8, font=("Consolas", 11)):
    frame = tk.Frame(parent, bg=C["border"], padx=1, pady=1)
    txt = tk.Text(frame, height=height, bg=C["editor"], fg=C["fg"], insertbackground=C["fg"],
                  relief="flat", font=font, wrap="none", padx=8, pady=6, undo=True,
                  selectbackground="#3b4a85", borderwidth=0)
    sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    return frame, txt



def parse_tests(text):
    
    tests = []
    blocks = re.split(r"(?m)^[ \t]*===[ \t]*$", text.replace("\r\n", "\n"))
    for n, block in enumerate(b for b in blocks if b.strip()):
        lines = block.strip("\n").split("\n")
        sep = next((i for i, ln in enumerate(lines) if ln.strip() == "---"), None)
        if sep is None:
            raise ValueError(f"в тесте №{n + 1} нет строки-разделителя ---")
        if any(ln.strip() == "---" for ln in lines[sep + 1:]):
            raise ValueError(f"в тесте №{n + 1} больше одного разделителя ---: "
                             "между тестами должна стоять строка ===")
        inp = "\n".join(lines[:sep]).strip("\n")
        out = "\n".join(lines[sep + 1:]).strip("\n")
        if not out.strip():
            raise ValueError(f"в тесте №{n + 1} пустой ожидаемый вывод")
        tests.append({"input": inp, "output": out})
    if not tests:
        raise ValueError("не задано ни одного теста")
    if len(tests) > MAX_TESTS:
        raise ValueError(f"тестов {len(tests)}, максимум {MAX_TESTS}")
    return tests


def tests_to_text(tests):
    return "\n===\n".join(f"{t['input']}\n---\n{t['output']}" for t in tests)


def parse_forbidden(text):
    words, seen = [], set()
    for w in re.split(r"[,;\n]+", text):
        w = w.strip()
        if w and w not in seen:
            seen.add(w)
            words.append(w)
    return words


TESTS_HINT = (
    "Формат: ввод --- вывод. Несколько тестов разделяйте строкой ===\n"
    "Пример:\n2\n3\n---\n5\n===\n10\n20\n---\n30"
)



class TeacherApp:
    def __init__(self, root):
        self.root = root
        root.title("Панель Учителя — ФО")
        root.geometry("1100x760")
        root.minsize(980, 680)
        apply_theme(root)

        self.drafts = []      
        self.cur = None       
        self.preview_photo = None

        self.title_var = tk.StringVar()
        self.points_var = tk.StringVar(value="10")
        self.forb_var = tk.StringVar()
        self.time_var = tk.StringVar(value="0")
        self.submit_var = tk.StringVar()
        self.image_rel = ""

        self._build()
        self._load_existing()

    
    def _build(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=20, pady=(16, 8))
        ttk.Label(top, text="Панель Учителя", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text=f"  до {MAX_TASKS} задач · до {MAX_TESTS} тестов на задачу",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))
        ttk.Entry(top, textvariable=self.time_var, width=6).pack(side="right")
        ttk.Label(top, text="Время на ФО, мин (0 — без ограничения):").pack(side="right", padx=(0, 8))

        sub = ttk.Frame(self.root)
        sub.pack(fill="x", padx=20, pady=(0, 4))
        ttk.Button(sub, text="Обзор…", command=self.choose_submit_dir).pack(side="right")
        ttk.Label(sub, text="Папка сдачи (общая папка для работ учеников, необязательно):",
                  style="Muted.TLabel").pack(side="left")
        ttk.Entry(sub, textvariable=self.submit_var).pack(side="left", fill="x", expand=True, padx=10)

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        
        left = ttk.Frame(body, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        self.count_lbl = ttk.Label(left, text="Задачи", style="Panel.TLabel", font=("Segoe UI", 11, "bold"))
        self.count_lbl.pack(anchor="w", pady=(0, 8))
        self.listbox = tk.Listbox(
            left, width=26, height=12, bg=C["editor"], fg=C["fg"], selectbackground=C["accent"],
            selectforeground="#fff", relief="flat", highlightthickness=0, activestyle="none",
            font=("Segoe UI", 11), exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        ttk.Button(left, text="＋  Добавить задачу", command=self.add_task).pack(fill="x", pady=(12, 6))
        ttk.Button(left, text="Удалить задачу", style="Danger.TButton", command=self.delete_task).pack(fill="x")

        
        right = ttk.Frame(body, style="Panel.TFrame", padding=16)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.columnconfigure(2, weight=0)
        right.rowconfigure(4, weight=1)

        ttk.Label(right, text="Название", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(right, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(right, text="Макс. баллы", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(right, textvariable=self.points_var, width=10).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=6)

        ttk.Label(right, text="Запрещённые слова", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(right, textvariable=self.forb_var).grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=6)
        ttk.Label(right, text="через запятую: if, while, for", style="Panel.TLabel",
                  foreground=C["muted"]).grid(row=3, column=1, sticky="w", padx=(12, 0))

        ttk.Label(right, text="Тесты", style="Panel.TLabel").grid(row=4, column=0, sticky="nw", pady=(10, 0))
        tframe, self.tests_txt = make_text(right, height=10)
        tframe.grid(row=4, column=1, sticky="nsew", padx=(12, 0), pady=(10, 0))
        ttk.Label(right, text=TESTS_HINT, style="Panel.TLabel", foreground=C["muted"],
                  justify="left").grid(row=4, column=2, sticky="nw", padx=(14, 0), pady=(10, 0))

        ttk.Label(right, text="Фото условия\n(обязательно)", style="Panel.TLabel").grid(
            row=5, column=0, sticky="nw", pady=(14, 0))
        imgbox = ttk.Frame(right, style="Panel.TFrame")
        imgbox.grid(row=5, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(14, 0))
        self.preview = tk.Label(imgbox, text="Нет изображения", bg=C["editor"], fg=C["muted"],
                                width=44, height=9, relief="flat")
        self.preview.pack(side="left")
        btns = ttk.Frame(imgbox, style="Panel.TFrame")
        btns.pack(side="left", padx=14, anchor="n")
        ttk.Button(btns, text="Выбрать скриншот…", command=self.choose_image).pack(anchor="w")
        self.img_name_lbl = ttk.Label(btns, text="", style="Panel.TLabel", foreground=C["muted"], wraplength=240)
        self.img_name_lbl.pack(anchor="w", pady=8)

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=20, pady=(8, 16))
        self.status = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.status.pack(side="left")
        ttk.Button(bottom, text="💾  Сохранить в tasks.json", style="Accent.TButton",
                   command=self.save_all).pack(side="right")
        ttk.Button(bottom, text="📊  Собрать итоги (Excel/CSV)", command=self.build_summary).pack(side="right", padx=10)

    
    def _blank(self):
        return {"title": "Новая задача", "points": "10", "forbidden": "", "tests": "", "image": ""}

    def _load_existing(self):
        if TASKS_FILE.exists():
            try:
                data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
                self.time_var.set(str(data.get("time_limit_minutes", 0)))
                self.submit_var.set(str(data.get("submit_dir", "") or ""))
                for t in data.get("tasks", [])[:MAX_TASKS]:
                    self.drafts.append({
                        "title": t.get("title", ""),
                        "points": str(t.get("max_points", 10)),
                        "forbidden": ", ".join(t.get("forbidden", [])),
                        "tests": tests_to_text(t.get("tests", [])),
                        "image": t.get("image", ""),
                    })
            except Exception as e:
                messagebox.showwarning("tasks.json", f"Не удалось прочитать существующий файл:\n{e}")
        self._refresh_list()
        if self.drafts:
            self.listbox.selection_set(0)
            self.cur = 0
            self._fill_form()
        else:
            self._fill_form()

    def _refresh_list(self):
        sel = self.cur
        self.listbox.delete(0, "end")
        for i, d in enumerate(self.drafts):
            self.listbox.insert("end", f"  {i + 1}.  {d['title'] or '(без названия)'}")
        self.count_lbl.config(text=f"Задачи ({len(self.drafts)}/{MAX_TASKS})")
        if sel is not None and sel < len(self.drafts):
            self.listbox.selection_set(sel)

    def _store_form(self):
        if self.cur is None or self.cur >= len(self.drafts):
            return
        self.drafts[self.cur].update(
            title=self.title_var.get().strip(),
            points=self.points_var.get().strip(),
            forbidden=self.forb_var.get().strip(),
            tests=self.tests_txt.get("1.0", "end").strip("\n"),
            image=self.image_rel,
        )
        label = f"  {self.cur + 1}.  {self.drafts[self.cur]['title'] or '(без названия)'}"
        self.listbox.delete(self.cur)
        self.listbox.insert(self.cur, label)
        self.listbox.selection_set(self.cur)

    def _fill_form(self):
        d = self.drafts[self.cur] if self.cur is not None and self.cur < len(self.drafts) else None
        self.title_var.set(d["title"] if d else "")
        self.points_var.set(d["points"] if d else "10")
        self.forb_var.set(d["forbidden"] if d else "")
        self.tests_txt.delete("1.0", "end")
        if d:
            self.tests_txt.insert("1.0", d["tests"])
        self.image_rel = d["image"] if d else ""
        self._show_preview()

    
    def _on_select(self, _e):
        sel = self.listbox.curselection()
        if not sel or sel[0] == self.cur:
            return
        self._store_form()
        self.cur = sel[0]
        self._fill_form()

    def add_task(self):
        if len(self.drafts) >= MAX_TASKS:
            messagebox.showinfo("Лимит", f"Можно создать не более {MAX_TASKS} задач.")
            return
        self._store_form()
        self.drafts.append(self._blank())
        self.cur = len(self.drafts) - 1
        self._refresh_list()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self.cur)
        self._fill_form()

    def delete_task(self):
        if self.cur is None:
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранную задачу?"):
            return
        self.drafts.pop(self.cur)
        self.cur = min(self.cur, len(self.drafts) - 1) if self.drafts else None
        self._refresh_list()
        if self.cur is not None:
            self.listbox.selection_set(self.cur)
        self._fill_form()

    def choose_image(self):
        if self.cur is None:
            messagebox.showinfo("Фото", "Сначала добавьте задачу.")
            return
        types = [("Изображения", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")] if HAS_PIL else [("PNG / GIF", "*.png *.gif")]
        path = filedialog.askopenfilename(title="Скриншот условия задачи", filetypes=types)
        if not path:
            return
        src = Path(path)
        IMG_DIR.mkdir(exist_ok=True)
        dst = IMG_DIR / f"task_{int(time.time())}_{src.stem[:20]}{src.suffix.lower()}"
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать файл:\n{e}")
            return
        self.image_rel = f"images/{dst.name}"
        self._show_preview()

    def _show_preview(self):
        self.preview_photo = None
        path = BASE / self.image_rel if self.image_rel else None
        if not path or not path.exists():
            self.preview.config(image="", text="Нет изображения", width=44, height=9)
            self.img_name_lbl.config(text="")
            return
        try:
            if HAS_PIL:
                img = Image.open(path)
                img.thumbnail((340, 200))
                self.preview_photo = ImageTk.PhotoImage(img)
            else:
                ph = tk.PhotoImage(file=str(path))
                k = max(1, -(-ph.width() // 340), -(-ph.height() // 200))
                self.preview_photo = ph.subsample(k, k)
            self.preview.config(image=self.preview_photo, text="", width=0, height=0)
            self.img_name_lbl.config(text=self.image_rel)
        except Exception as e:
            self.preview.config(image="", text=f"Не удалось открыть:\n{e}", width=44, height=9)

    
    def choose_submit_dir(self):
        start = self.submit_var.get().strip()
        path = filedialog.askdirectory(title="Папка сдачи", initialdir=start if start and Path(start).is_dir() else str(BASE))
        if path:
            self.submit_var.set(path)

    def build_summary(self):
       
        start = self.submit_var.get().strip()
        if not start or not Path(start).is_dir():
            start = str(BASE / "reports") if (BASE / "reports").is_dir() else str(BASE)
        folder = filedialog.askdirectory(title="Папка с результатами учеников (где лежат result_*.json)", initialdir=start)
        if not folder:
            return
        try:
            rows, problems = exporter.collect_results(folder)
            if not rows:
                messagebox.showwarning("Итоги", "В выбранной папке нет файлов result_*.json.\n"
                                                "Их создаёт student.py, когда ученик сдаёт работу.")
                return
            files, warns = exporter.write_summaries(rows, folder)
        except OSError as e:
            messagebox.showerror("Итоги", f"Не удалось записать файлы:\n{e}")
            return
        lines = [f"Учеников в списке: {len(rows)}", f"Групп: {len({r['group'] for r in rows})}", "",
                 "Созданы файлы:"] + [f"   {Path(f).name}" for f in files] + ["", f"Папка: {folder}"]
        if problems or warns:
            lines += ["", "Внимание:"] + [f"   {p}" for p in problems + warns]
        messagebox.showinfo("Итоги готовы", "\n".join(lines))
        self.status.config(text=f"✔ Итоги: {len(rows)} учеников → {Path(folder).name}", foreground=C["ok"])
        if hasattr(os, "startfile") and messagebox.askyesno("Итоги", "Открыть папку с файлами?"):
            os.startfile(folder)

    
    def save_all(self):
        self._store_form()
        if not self.drafts:
            messagebox.showwarning("Нет задач", "Добавьте хотя бы одну задачу.")
            return
        tasks = []
        for i, d in enumerate(self.drafts, 1):
            try:
                if not d["title"]:
                    raise ValueError("не указано название")
                try:
                    pts = int(d["points"])
                except ValueError:
                    raise ValueError("баллы должны быть целым числом")
                if pts <= 0:
                    raise ValueError("баллы должны быть больше нуля")
                tests = parse_tests(d["tests"])
                if not d["image"] or not (BASE / d["image"]).exists():
                    raise ValueError("не прикреплено фото условия (оно обязательно)")
            except ValueError as e:
                messagebox.showerror("Проверьте данные", f"Задача №{i}: {e}")
                self.cur = i - 1
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(self.cur)
                self._fill_form()
                return
            tasks.append({
                "title": d["title"],
                "max_points": pts,
                "forbidden": parse_forbidden(d["forbidden"]),
                "tests": tests,
                "image": d["image"],
            })
        try:
            minutes = int(self.time_var.get().strip() or "0")
            if minutes < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Проверьте данные", "Время должно быть целым числом минут (0 — без ограничения).")
            return
        try:
            TASKS_FILE.write_text(json.dumps({"version": 1, "time_limit_minutes": minutes,
                                              "submit_dir": self.submit_var.get().strip(), "tasks": tasks},
                                             ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Ошибка записи", str(e))
            return
        self.status.config(text=f"✔ Сохранено задач: {len(tasks)}, время: {minutes or 'без ограничения'} → {TASKS_FILE.name}", foreground=C["ok"])


def main():
    root = tk.Tk()
    TeacherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()