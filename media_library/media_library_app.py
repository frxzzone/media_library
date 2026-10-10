import csv
import hashlib
import json
import os
import platform
import subprocess
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "library.json"
MEDIA_EXTENSIONS = {
    "Аудио": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "Видео": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v", ".mpeg", ".mpg"},
    "Изображение": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg"},
}
ALL_TYPES = ["Все типы", *MEDIA_EXTENSIONS.keys()]


def detect_type(path):
    ext = Path(path).suffix.lower()
    return next((kind for kind, extensions in MEDIA_EXTENSIONS.items() if ext in extensions), None)


def human_size(size):
    value = float(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{int(value)} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_metadata(path):
    stat = path.stat()
    item = {
        "name": path.name, "path": str(path.resolve()), "folder": str(path.parent.resolve()),
        "type": detect_type(path), "extension": path.suffix.lower(), "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Optional metadata support when Mutagen is installed.
    if item["type"] == "Аудио":
        try:
            from mutagen import File as MutagenFile
            media = MutagenFile(str(path), easy=True)
            if media:
                item["artist"] = ", ".join(media.get("artist", []))
                item["album"] = ", ".join(media.get("album", []))
                item["duration"] = round(media.info.length, 1) if getattr(media, "info", None) else ""
        except Exception:
            pass
    return item


class MediaLibraryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Медиатека — локальный каталог")
        self.geometry("1280x800")
        self.minsize(980, 620)
        self.role = None
        self.folders, self.items, self.playlists = [], {}, {}
        self.view_mode = "list"
        self.visible_items = []
        self.status = tk.StringVar(value="Выберите роль для входа")
        self.load_data()
        self.show_login()

    def load_data(self):
        if not DATA_FILE.exists():
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self.folders = data.get("folders", [])
            self.playlists = data.get("playlists", {})
            raw_items = data.get("items", {})
            # Migrate the previous version, which only stored folders.
            if isinstance(raw_items, list):
                raw_items = {x.get("path", ""): x for x in raw_items if x.get("path")}
            self.items = raw_items if isinstance(raw_items, dict) else {}
        except (OSError, json.JSONDecodeError):
            messagebox.showwarning("Медиатека", "Не удалось прочитать library.json. Будет создан новый каталог.")

    def save_data(self):
        payload = {"folders": self.folders, "items": self.items, "playlists": self.playlists}
        temp = DATA_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(DATA_FILE)

    def clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def show_login(self):
        self.clear()
        frame = ttk.Frame(self, padding=40)
        frame.place(relx=.5, rely=.5, anchor="center")
        ttk.Label(frame, text="Медиатека", font=("TkDefaultFont", 28, "bold")).pack(pady=(0, 10))
        ttk.Label(frame, text="Локальный каталог музыки, видео, изображений и учебных материалов").pack(pady=(0, 25))
        ttk.Label(frame, text="Выберите роль").pack(pady=(0, 8))
        ttk.Button(frame, text="Пользователь", command=lambda: self.enter("Пользователь")).pack(fill="x", pady=5)
        ttk.Button(frame, text="Администратор", command=lambda: self.enter("Администратор")).pack(fill="x", pady=5)
        ttk.Label(frame, text="Учебная версия: вход по роли без пароля; это не система защиты доступа.",
                  foreground="#666").pack(pady=(18, 0))

    def enter(self, role):
        self.role = role
        self.show_main()
        self.scan_all()

    def show_main(self):
        self.clear()
        top = ttk.Frame(self, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Медиатека", font=("TkDefaultFont", 20, "bold")).pack(side="left")
        ttk.Label(top, text=f"Роль: {self.role}").pack(side="left", padx=18)
        ttk.Button(top, text="Сменить роль", command=self.show_login).pack(side="right")

        controls = ttk.Frame(self, padding=(12, 4))
        controls.pack(fill="x")
        self.add_btn = ttk.Button(controls, text="Добавить папку", command=self.add_folder)
        self.add_btn.pack(side="left")
        self.remove_btn = ttk.Button(controls, text="Удалить папку", command=self.remove_folder)
        self.remove_btn.pack(side="left", padx=5)
        ttk.Button(controls, text="Пересканировать", command=self.scan_all).pack(side="left", padx=5)
        ttk.Button(controls, text="Список", command=lambda: self.set_view("list")).pack(side="left", padx=(16, 3))
        ttk.Button(controls, text="Сетка", command=lambda: self.set_view("grid")).pack(side="left")
        ttk.Button(controls, text="Дубликаты", command=self.show_duplicates).pack(side="left", padx=(16, 3))
        ttk.Button(controls, text="Статистика", command=self.show_stats).pack(side="left", padx=3)
        ttk.Button(controls, text="Экспорт", command=self.export_data).pack(side="left", padx=3)
        if self.role != "Администратор":
            self.add_btn.state(["disabled"])
            self.remove_btn.state(["disabled"])

        folders_box = ttk.LabelFrame(self, text="Подключённые папки", padding=6)
        folders_box.pack(fill="x", padx=12, pady=(5, 2))
        self.folder_list = tk.Listbox(folders_box, height=2, exportselection=False)
        self.folder_list.pack(fill="x")

        filters = ttk.LabelFrame(self, text="Поиск и фильтры", padding=8)
        filters.pack(fill="x", padx=12, pady=6)
        self.search_var = tk.StringVar()
        self.type_var = tk.StringVar(value="Все типы")
        self.fav_var = tk.BooleanVar(value=False)
        self.tag_var = tk.StringVar()
        self.folder_var = tk.StringVar(value="Все папки")
        ttk.Label(filters, text="Поиск").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(filters, textvariable=self.search_var, width=28)
        search.grid(row=0, column=1, padx=(4, 12), sticky="ew")
        search.bind("<KeyRelease>", lambda _e: self.refresh_view())
        ttk.Label(filters, text="Тип").grid(row=0, column=2, sticky="w")
        type_box = ttk.Combobox(filters, textvariable=self.type_var, values=ALL_TYPES, state="readonly", width=15)
        type_box.grid(row=0, column=3, padx=(4, 12))
        type_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_view())
        ttk.Label(filters, text="Папка").grid(row=0, column=4, sticky="w")
        self.folder_box = ttk.Combobox(filters, textvariable=self.folder_var, state="readonly", width=32)
        self.folder_box.grid(row=0, column=5, padx=(4, 12))
        self.folder_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_view())
        ttk.Label(filters, text="Тег").grid(row=0, column=6, sticky="w")
        tag_entry = ttk.Entry(filters, textvariable=self.tag_var, width=16)
        tag_entry.grid(row=0, column=7, padx=(4, 8))
        tag_entry.bind("<KeyRelease>", lambda _e: self.refresh_view())
        ttk.Checkbutton(filters, text="Только избранное", variable=self.fav_var,
                        command=self.refresh_view).grid(row=0, column=8, sticky="w")
        filters.columnconfigure(1, weight=1)

        self.content = ttk.Frame(self, padding=(12, 4))
        self.content.pack(fill="both", expand=True)
        actions = ttk.Frame(self, padding=(12, 3))
        actions.pack(fill="x")
        ttk.Button(actions, text="Открыть", command=self.open_selected).pack(side="left")
        ttk.Button(actions, text="Избранное ★", command=self.toggle_favorite).pack(side="left", padx=4)
        ttk.Button(actions, text="Оценить", command=self.rate_selected).pack(side="left", padx=4)
        ttk.Button(actions, text="Теги", command=self.edit_tags).pack(side="left", padx=4)
        ttk.Button(actions, text="В плейлист", command=self.add_to_playlist).pack(side="left", padx=4)
        ttk.Button(actions, text="Новый плейлист", command=self.create_playlist).pack(side="left", padx=4)
        ttk.Button(actions, text="Плейлисты", command=self.manage_playlists).pack(side="left", padx=4)
        ttk.Label(self, textvariable=self.status, anchor="w", padding=8).pack(fill="x")
        self.refresh_folder_list()
        self.refresh_view()

    def refresh_folder_list(self):
        if not hasattr(self, "folder_list"):
            return
        self.folder_list.delete(0, tk.END)
        for folder in self.folders:
            self.folder_list.insert(tk.END, folder)
        if hasattr(self, "folder_box"):
            values = ["Все папки"] + self.folders
            self.folder_box.configure(values=values)
            if self.folder_var.get() not in values:
                self.folder_var.set("Все папки")

    def add_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку с медиафайлами")
        if folder:
            folder = str(Path(folder).resolve())
            if folder not in self.folders:
                self.folders.append(folder)
                self.save_data()
            self.refresh_folder_list()
            self.scan_all()

    def remove_folder(self):
        selection = self.folder_list.curselection()
        if not selection:
            messagebox.showinfo("Папки", "Сначала выберите папку в списке.")
            return
        folder = self.folders.pop(selection[0])
        self.save_data()
        self.refresh_folder_list()
        self.scan_all()

    def scan_all(self):
        found = {}
        for folder in self.folders:
            root = Path(folder)
            if not root.is_dir():
                continue
            try:
                for path in root.rglob("*"):
                    try:
                        if path.is_file() and detect_type(path):
                            key = str(path.resolve())
                            metadata = file_metadata(path)
                            old = self.items.get(key, {})
                            metadata.update({k: old[k] for k in ("tags", "favorite", "rating", "hash") if k in old})
                            found[key] = metadata
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                continue
        self.items.update(found)
        # Keep entries for disconnected/missing files in saved data, but only show files still found.
        self.current_paths = set(found)
        self.save_data()
        self.refresh_folder_list()
        self.refresh_view()
        self.status.set(f"Файлов: {len(found)} | Папок: {len(self.folders)}")

    def filtered_items(self):
        query = self.search_var.get().strip().casefold()
        kind = self.type_var.get()
        folder = self.folder_var.get()
        tag = self.tag_var.get().strip().casefold()
        results = []
        for path in getattr(self, "current_paths", set(self.items)):
            item = self.items.get(path)
            if not item:
                continue
            tags = item.get("tags", [])
            haystack = " ".join([item.get("name", ""), item.get("folder", ""), " ".join(tags),
                                 item.get("artist", ""), item.get("album", "")]).casefold()
            if query and query not in haystack:
                continue
            if kind != "Все типы" and item.get("type") != kind:
                continue
            if folder != "Все папки" and item.get("folder") != folder:
                continue
            if tag and not any(tag in t.casefold() for t in tags):
                continue
            if self.fav_var.get() and not item.get("favorite", False):
                continue
            results.append(item)
        return sorted(results, key=lambda x: x.get("name", "").casefold())

    def refresh_view(self):
        if not hasattr(self, "content"):
            return
        self.visible_items = self.filtered_items()
        if self.view_mode == "list":
            self.build_list_view()
        else:
            self.build_grid_view()
        self.status.set(f"Показано: {len(self.visible_items)} | Всего в каталоге: {len(getattr(self, 'current_paths', set(self.items)))}")

    def build_list_view(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        columns = ("name", "type", "folder", "size", "tags", "rating", "favorite", "modified")
        self.tree = ttk.Treeview(self.content, columns=columns, show="headings", selectmode="browse")
        labels = {"name": "Название", "type": "Тип", "folder": "Папка", "size": "Размер",
                  "tags": "Теги", "rating": "Оценка", "favorite": "★", "modified": "Изменён"}
        widths = {"name": 230, "type": 100, "folder": 260, "size": 90, "tags": 150,
                  "rating": 65, "favorite": 45, "modified": 140}
        for col in columns:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=widths[col], anchor="w")
        scroll_y = ttk.Scrollbar(self.content, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(self.content, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.path_by_iid = {}
        for item in self.visible_items:
            path = item["path"]
            iid = self.tree.insert("", "end", values=(item["name"], item["type"], item["folder"],
                human_size(item.get("size", 0)), ", ".join(item.get("tags", [])), item.get("rating", 0),
                "★" if item.get("favorite") else "", item.get("modified", "")))
            self.path_by_iid[iid] = path
        self.tree.bind("<Double-1>", self.open_selected)

    def build_grid_view(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        canvas = tk.Canvas(self.content, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        cols = 4
        for i, item in enumerate(self.visible_items):
            card = ttk.LabelFrame(inner, text=item.get("type", "Файл"), padding=10)
            card.grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky="nsew")
            icon = {"Аудио": "♫", "Видео": "▶", "Изображение": "▣"}.get(item.get("type"), "•")
            ttk.Label(card, text=icon, font=("TkDefaultFont", 24)).pack()
            ttk.Label(card, text=item.get("name", ""), wraplength=190, justify="center").pack()
            ttk.Label(card, text=human_size(item.get("size", 0))).pack(pady=3)
            ttk.Label(card, text=("★ " if item.get("favorite") else "") +
                      ("★" * int(item.get("rating", 0)))).pack()
            ttk.Button(card, text="Открыть", command=lambda p=item["path"]: self.open_path(p)).pack(pady=4)

    def set_view(self, mode):
        self.view_mode = mode
        self.refresh_view()

    def selected_item(self):
        if self.view_mode != "list" or not hasattr(self, "tree"):
            messagebox.showinfo("Файл", "Для этой операции переключитесь в режим «Список» и выберите файл.")
            return None
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Файл", "Сначала выберите файл в списке.")
            return None
        return self.items.get(self.path_by_iid.get(selection[0], ""))

    def open_selected(self, _event=None):
        item = self.selected_item()
        if item:
            self.open_path(item["path"])

    def open_path(self, path):
        try:
            if not Path(path).is_file():
                messagebox.showerror("Ошибка", "Файл не найден. Пересканируйте библиотеку.")
                return
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{exc}")

    def mutate_selected(self, callback):
        item = self.selected_item()
        if not item:
            return
        callback(item)
        self.save_data()
        self.refresh_view()

    def toggle_favorite(self):
        self.mutate_selected(lambda item: item.update(favorite=not item.get("favorite", False)))

    def rate_selected(self):
        item = self.selected_item()
        if not item:
            return
        value = simpledialog.askinteger("Оценка", "Введите оценку от 0 до 5:", minvalue=0, maxvalue=5, parent=self)
        if value is not None:
            item["rating"] = value
            self.save_data()
            self.refresh_view()

    def edit_tags(self):
        item = self.selected_item()
        if not item:
            return
        current = ", ".join(item.get("tags", []))
        value = simpledialog.askstring("Теги", "Введите теги через запятую:", initialvalue=current, parent=self)
        if value is not None:
            item["tags"] = list(dict.fromkeys(x.strip() for x in value.split(",") if x.strip()))
            self.save_data()
            self.refresh_view()

    def create_playlist(self):
        name = simpledialog.askstring("Новый плейлист", "Название плейлиста:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.playlists:
            messagebox.showwarning("Плейлист", "Плейлист с таким названием уже существует.")
            return
        self.playlists[name] = []
        self.save_data()
        messagebox.showinfo("Плейлист", f"Создан плейлист «{name}».")

    def add_to_playlist(self):
        item = self.selected_item()
        if not item:
            return
        if not self.playlists:
            messagebox.showinfo("Плейлисты", "Сначала создайте плейлист.")
            return
        names = list(self.playlists)
        dialog = tk.Toplevel(self)
        dialog.title("Добавить в плейлист")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Выберите плейлист:").pack(padx=16, pady=(14, 5))
        choice = tk.StringVar(value=names[0])
        ttk.Combobox(dialog, textvariable=choice, values=names, state="readonly", width=32).pack(padx=16, pady=5)
        def add():
            playlist = choice.get()
            if item["path"] not in self.playlists[playlist]:
                self.playlists[playlist].append(item["path"])
            self.save_data()
            dialog.destroy()
            messagebox.showinfo("Плейлист", f"Файл добавлен в «{playlist}».")
        ttk.Button(dialog, text="Добавить", command=add).pack(pady=(5, 14))

    def manage_playlists(self):
        if not self.playlists:
            messagebox.showinfo("Плейлисты", "Плейлистов пока нет.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Плейлисты")
        dialog.geometry("620x360")
        box = ttk.Treeview(dialog, columns=("name", "count"), show="headings")
        box.heading("name", text="Плейлист")
        box.heading("count", text="Файлов")
        box.pack(fill="both", expand=True, padx=10, pady=10)
        for name, paths in self.playlists.items():
            box.insert("", "end", values=(name, len(paths)))
        def open_playlist(_event=None):
            sel = box.selection()
            if not sel:
                return
            name = box.item(sel[0], "values")[0]
            paths = self.playlists.get(name, [])
            files = [self.items[p] for p in paths if p in self.items]
            messagebox.showinfo(name, "\n".join(x["name"] for x in files) or "Нет доступных файлов.")
        box.bind("<Double-1>", open_playlist)
        ttk.Label(dialog, text="Дважды щёлкните плейлист, чтобы увидеть его файлы.").pack(pady=(0, 8))

    def show_duplicates(self):
        candidates = list(self.filtered_items())
        groups = {}
        for item in candidates:
            size = item.get("size", 0)
            if size:
                groups.setdefault(size, []).append(item)
        possible = [group for group in groups.values() if len(group) > 1]
        if not possible:
            messagebox.showinfo("Дубликаты", "Кандидатов по размеру не найдено.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Поиск дубликатов")
        dialog.geometry("900x460")
        ttk.Label(dialog, text="Сначала сравнивается размер, затем SHA-256 содержимого. Хеширование может занять время.",
                  wraplength=850).pack(anchor="w", padx=10, pady=8)
        tree = ttk.Treeview(dialog, columns=("name", "size", "path", "hash"), show="headings")
        for col, title, width in (("name", "Название", 200), ("size", "Размер", 90), ("path", "Путь", 400), ("hash", "SHA-256", 180)):
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=5)
        def calculate():
            exact = {}
            errors = 0
            for group in possible:
                for item in group:
                    try:
                        digest = item.get("hash") or file_hash(item["path"])
                        item["hash"] = digest
                        exact.setdefault((item.get("size", 0), digest), []).append(item)
                    except OSError:
                        errors += 1
            for group in exact.values():
                if len(group) > 1:
                    for item in group:
                        tree.insert("", "end", values=(item["name"], human_size(item.get("size", 0)),
                                                       item["path"], item["hash"][:20] + "…"))
            self.save_data()
            count = sum(1 for group in exact.values() if len(group) > 1)
            messagebox.showinfo("Дубликаты", f"Групп совпадений: {count}. Ошибок чтения: {errors}.", parent=dialog)
        ttk.Button(dialog, text="Вычислить хеши и найти совпадения", command=calculate).pack(pady=8)

    def show_stats(self):
        items = [self.items[p] for p in getattr(self, "current_paths", set(self.items)) if p in self.items]
        by_type = {}
        total_size = 0
        for item in items:
            by_type[item.get("type", "Другое")] = by_type.get(item.get("type", "Другое"), 0) + 1
            total_size += item.get("size", 0)
        lines = [f"Всего файлов: {len(items)}", f"Общий объём: {human_size(total_size)}",
                 f"Подключено папок: {len(self.folders)}", f"Избранное: {sum(bool(x.get('favorite')) for x in items)}",
                 f"Плейлистов: {len(self.playlists)}", "", "По типам:"]
        lines.extend(f"  {kind}: {count}" for kind, count in sorted(by_type.items()))
        messagebox.showinfo("Статистика библиотеки", "\n".join(lines))

    def export_data(self):
        path = filedialog.asksaveasfilename(title="Экспорт библиотеки",
            defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("JSON", "*.json")])
        if not path:
            return
        records = self.filtered_items()
        try:
            if Path(path).suffix.lower() == ".json":
                Path(path).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                fields = ["name", "path", "folder", "type", "extension", "size", "modified",
                          "tags", "favorite", "rating", "artist", "album", "duration"]
                with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    for item in records:
                        row = dict(item)
                        row["tags"] = ", ".join(row.get("tags", []))
                        writer.writerow(row)
            messagebox.showinfo("Экспорт", f"Экспортировано файлов: {len(records)}\n{path}")
        except OSError as exc:
            messagebox.showerror("Экспорт", f"Не удалось сохранить файл:\n{exc}")


if __name__ == "__main__":
    MediaLibraryApp().mainloop()
