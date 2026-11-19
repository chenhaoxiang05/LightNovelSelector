"""Linux desktop for the shared LightNovelSelector application service."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# The installed archive and the source checkout have the same layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightnovel_selector.application import ApplicationService
from linux.history import ReportHistory

PAGE_SIZE = 200


def display(value: str) -> str:
    # POSIX filenames can contain bytes decoded as lone surrogates, which Tcl rejects.
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


class LibraryWindow:
    def __init__(self, root: tk.Tk, service: ApplicationService):
        self.root = root
        self.service = service
        self.revision = -1
        self.log_cursor = 0
        self.plans = []
        self.filtered_plans = []
        self.filter_key = None
        self.movable = 0
        self.page = 0
        self.poll_id = None
        self.closing = False
        self.filter_id = None
        self.state = {}
        self.folder = tk.StringVar()
        self.search = tk.StringVar()
        self.options = {key: tk.BooleanVar() for key in ("recursive", "auto_rename", "use_network")}
        self.status_filter = tk.StringVar(value="全部状态")
        self.message = tk.StringVar()
        self.summary = tk.StringVar()
        self.page_label = tk.StringVar()

        root.title("LightNovelSelector · 轻小说整理")
        root.geometry("1040x680")
        root.minsize(680, 540)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self._build()
        self.refresh()
        root.bind("<Control-o>", lambda _: self.pick_folder())
        root.bind("<Control-f>", self.focus_search)
        root.bind("<F5>", lambda _: self.scan())
        root.bind("<Control-Return>", lambda _: self.confirm_apply())

    def _build(self):
        body = ttk.Frame(self.root, padding=16)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        top = ttk.Frame(body)
        top.grid(row=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        self.choose = ttk.Button(top, text="选择目录…", command=self.pick_folder)
        self.choose.grid(row=0, column=0)
        ttk.Entry(top, state="readonly", textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=8)
        self.history = ttk.Button(top, text="整理历史", command=self.open_history)
        self.history.grid(row=0, column=2)

        actions = ttk.Frame(body)
        actions.grid(row=1, sticky="ew", pady=(12, 8))
        self.scan_button = ttk.Button(actions, text="扫描预览", command=self.scan)
        self.scan_button.pack(side="left")
        self.cancel = ttk.Button(actions, text="取消扫描", command=lambda: self.run(self.service.cancel_operation))
        self.cancel.pack(side="left", padx=(6, 12))
        self.switches = []
        for key, label in (("recursive", "包含子目录"), ("auto_rename", "规范文件名"), ("use_network", "联网识别")):
            box = ttk.Checkbutton(actions, text=label, variable=self.options[key], command=self.save_options)
            box.pack(side="left", padx=(0, 8))
            self.switches.append(box)

        ttk.Separator(body).grid(row=2, sticky="ew", pady=(0, 10))
        filters = ttk.Frame(body)
        filters.grid(row=3, sticky="ew", pady=(0, 6))
        filters.columnconfigure(1, weight=1)
        ttk.Label(filters, text="搜索预览").grid(row=0, column=0)
        self.search_entry = ttk.Entry(filters, textvariable=self.search)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.status_box = ttk.Combobox(filters, textvariable=self.status_filter, width=10, state="readonly")
        self.status_box.grid(row=0, column=2)
        self.search.trace_add("write", lambda *_: self.schedule_filter())
        self.status_box.bind("<<ComboboxSelected>>", lambda _: self.schedule_filter())

        table = ttk.Frame(body)
        table.grid(row=4, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table, columns=("file", "series", "confidence", "status"), show="headings", selectmode="browse", height=8
        )
        for key, label, width in (
            ("file", "文件名", 330),
            ("series", "系列", 210),
            ("confidence", "置信度", 80),
            ("status", "状态", 86),
        ):
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(key, width=width, minwidth=64, stretch=key in {"file", "series"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, command=self.tree.yview, orient="vertical")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_detail())
        self.tree.bind("<Return>", lambda _: self.edit())

        paging = ttk.Frame(body)
        paging.grid(row=5, sticky="ew", pady=6)
        self.previous = ttk.Button(paging, text="上一页", command=lambda: self.render_page(self.page - 1))
        self.following = ttk.Button(paging, text="下一页", command=lambda: self.render_page(self.page + 1))
        for widget in (self.following, self.previous):
            widget.pack(side="right", padx=(6, 0))
        ttk.Label(paging, textvariable=self.page_label).pack(side="left")

        info = ttk.LabelFrame(body, text="所选文件", padding=(8, 6))
        info.grid(row=6, sticky="ew")
        info.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(
            info,
            height=4,
            width=10,
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            font="TkDefaultFont",
            state="disabled",
            takefocus=True,
        )
        self.detail_text.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(info, orient="vertical", command=self.detail_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=scrollbar.set)
        self.edit_button = ttk.Button(info, text="修正系列…", command=self.edit)
        self.edit_button.grid(row=0, column=2, padx=(8, 0))

        bottom = ttk.Frame(body)
        bottom.grid(row=7, sticky="ew", pady=(12, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.summary).grid(row=0, column=0, sticky="w")
        self.apply = ttk.Button(bottom, text="确认整理…", command=self.confirm_apply)
        self.apply.grid(row=0, column=1, rowspan=2)
        ttk.Label(bottom, textvariable=self.message, wraplength=580).grid(row=1, column=0, sticky="w")
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.grid(row=8, sticky="ew", pady=(6, 0))

    @staticmethod
    def enable(widget, enabled):
        widget.state(["!disabled"] if enabled else ["disabled"])

    def run(self, action, *args, **kwargs):
        snapshot = None
        try:
            result = action(*args, **kwargs)
            snapshot = result if "plans_revision" in result else result.get("snapshot", result.get("state"))
            return result
        except (OSError, ValueError, RuntimeError, IndexError) as error:
            messagebox.showerror("操作未完成", display(str(error)), parent=self.root)
            return None
        finally:
            self.refresh(snapshot)

    def refresh(self, snapshot=None):
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.state = snapshot if snapshot is not None else self.service.snapshot(self.log_cursor, self.revision)
        state = self.state
        self.log_cursor = state["log_cursor"]
        self.folder.set(display(state["folder"]))
        for key, variable in self.options.items():
            variable.set(state["settings"][key])
        op = state["operation"]
        running = op["state"] == "running"
        if state["plans"] is not None and self.revision != state["plans_revision"]:
            self.revision = state["plans_revision"]
            self.plans = state["plans"]
            self.movable = sum(row["will_move"] for row in self.plans)
            labels = ["全部状态", *sorted({row["status_label"] for row in self.plans})]
            self.status_box.configure(values=labels)
            if self.status_filter.get() not in labels:
                self.status_filter.set(labels[0])
            self.render_page(self.page)
        self.enable(self.choose, not running)
        self.enable(self.history, bool(state["folder"]) and not running)
        self.enable(self.scan_button, bool(state["folder"]) and not running)
        self.enable(self.cancel, running and op["can_cancel"])
        self.enable(self.apply, bool(self.movable) and not running)
        for widget in self.switches:
            self.enable(widget, not running)
        self.update_edit_button()
        counts = state["counts"]
        self.summary.set(
            f"共 {counts['total']} 个文件　·　可整理 {counts['ready']}　·　重复 {counts['duplicate']}　·　错误 {counts['error']}"
        )
        self.message.set(display(op["message"] + (f"：{op['error']}" if op["error"] else "")))
        self.progress.configure(maximum=max(1, op["total"]), value=op["done"])
        if self.closing and not running:
            self.root.destroy()
        elif running:
            self.poll_id = self.root.after(180, self.refresh)

    def schedule_filter(self):
        if self.filter_id is not None:
            self.root.after_cancel(self.filter_id)
        self.filter_id = self.root.after(120, self.apply_filter)

    def apply_filter(self):
        self.filter_id = None
        self.render_page(0)

    def matching_plans(self):
        query = self.search.get().strip().casefold()
        status = self.status_filter.get()
        key = (self.revision, query, status)
        if key != self.filter_key:
            if not query and status == "全部状态":
                self.filtered_plans = self.plans
            else:
                self.filtered_plans = [
                    row
                    for row in self.plans
                    if (status == "全部状态" or row["status_label"] == status)
                    and (not query or query in row["file_name"].casefold() or query in row["series_name"].casefold())
                ]
            self.filter_key = key
        return self.filtered_plans

    def render_page(self, page):
        old = self.tree.selection()
        matches = self.matching_plans()
        last = max(0, (len(matches) - 1) // PAGE_SIZE)
        self.page = min(max(0, page), last)
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        start = self.page * PAGE_SIZE
        for row in matches[start : start + PAGE_SIZE]:
            self.tree.insert(
                "",
                "end",
                iid=str(row["index"]),
                values=(
                    display(row["file_name"]),
                    display(row["series_name"]),
                    row["confidence_label"],
                    row["status_label"],
                ),
            )
        if old and self.tree.exists(old[0]):
            self.tree.selection_set(old[0])
        self.page_label.set(
            f"显示 {start + 1}–{min(start + PAGE_SIZE, len(matches))} / {len(matches)} 个结果"
            if matches
            else "没有匹配的文件"
        )
        self.enable(self.previous, self.page > 0)
        self.enable(self.following, self.page < last)
        self.show_detail()

    def selected(self):
        rows = self.tree.selection()
        return self.plans[int(rows[0])] if rows else None

    def update_edit_button(self):
        row = self.selected()
        self.enable(
            self.edit_button,
            row is not None and row["status"] != "moved" and self.state["operation"]["state"] != "running",
        )

    def show_detail(self):
        row = self.selected()
        lines = ["选择文件可查看完整路径和分类依据。"]
        if row:
            lines = [
                f"原路径　{row['source_path']}",
                f"目标　　{row['target_path']}",
                f"识别　　{row['resolver_source']}　{row['classification_reason']}",
                f"书籍　　{row['book_title']}　·　{row['authors_label']}　·　{row['volume_label']}　·　{row['language_label']}",
            ]
            lines.extend(row["classification_evidence"])
            if row["note"]:
                lines.append(row["note"])
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", display("\n".join(lines)))
        self.detail_text.configure(state="disabled")
        self.update_edit_button()

    def edit(self):
        if self.edit_button.instate(["disabled"]):
            return
        row = self.selected()
        revision = self.revision
        name = simpledialog.askstring(
            "修正系列",
            f"为「{display(row['file_name'])}」指定系列名",
            initialvalue=display(row["series_name"]),
            parent=self.root,
        )
        if name is not None:
            self.run(self.service.edit_plans, row["index"], name, scope="single", expected_plans_revision=revision)

    def focus_search(self, _event):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def pick_folder(self):
        if self.choose.instate(["disabled"]):
            return
        folder = filedialog.askdirectory(
            parent=self.root, title="选择轻小说目录", mustexist=True, initialdir=self.state["folder"] or None
        )
        if folder:
            self.run(self.service.set_folder, folder)

    def save_options(self):
        settings = dict(self.state["settings"])
        settings.update({key: variable.get() for key, variable in self.options.items()})
        result = self.run(self.service.save_settings, settings)
        if result and result["warning"]:
            messagebox.showwarning("设置仅在本次生效", display(result["warning"]), parent=self.root)

    def scan(self):
        if not self.scan_button.instate(["disabled"]):
            self.run(self.service.start_scan)

    def confirm_apply(self):
        if self.apply.instate(["disabled"]):
            return
        counts = self.state["counts"]
        if messagebox.askyesno(
            "确认整理全部预览",
            f"{self.folder.get()}\n\n将按完整预览移动 {self.movable} 个文件，"
            f"其余 {counts['total'] - self.movable} 个跳过。搜索、筛选和分页仅影响显示。"
            "\n\n执行后可在整理历史中撤销。",
            parent=self.root,
            default="no",
        ):
            self.run(self.service.start_apply)

    def open_history(self):
        if not self.history.instate(["disabled"]):
            ReportHistory(self.root, self.service, self.refresh)

    def close(self):
        if self.closing:
            return
        for window in self.root.winfo_children():
            if isinstance(window, ReportHistory):
                window.lift()
                return
        if self.service.is_critical_operation():
            messagebox.showinfo("正在整理文件", "请等待文件操作完成后关闭。", parent=self.root)
            return
        if self.service.is_operation_running():
            self.closing = True
            self.run(self.service.cancel_operation)
        else:
            self.root.destroy()


def main():
    root = tk.Tk(className="LightNovelSelector")
    LibraryWindow(root, ApplicationService())
    root.mainloop()


if __name__ == "__main__":
    main()
