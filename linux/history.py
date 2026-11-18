"""Read validated reports and request undo through the shared core."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk


class ReportHistory(tk.Toplevel):
    def __init__(self, root, service, refresh):
        super().__init__(root)
        self.service = service
        self.refresh = refresh
        self.reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report-reader")
        self.read_job = None
        self.timer = None
        self.records = {}
        self.title("整理历史")
        self.transient(root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.geometry("740x480")
        self.minsize(480, 300)
        self.grab_set()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        table = ttk.Frame(self, padding=(12, 12, 12, 0))
        table.grid(sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.rows = ttk.Treeview(table, columns=("date", "moved", "skipped", "status"), show="headings",
                                 height=6, selectmode="browse")
        for key, label, width in (("date", "整理时间", 220), ("moved", "已移动", 70), ("skipped", "已跳过", 70),
                                  ("status", "状态", 80)):
            self.rows.heading(key, text=label, anchor="w")
            self.rows.column(key, width=width)
        self.rows.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(table, orient="vertical", command=self.rows.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.rows.configure(yscrollcommand=bar.set)
        self.rows.bind("<<TreeviewSelect>>", lambda _: self.select())

        details = ttk.LabelFrame(self, text="报告条目", padding=6)
        details.grid(row=1, column=0, padx=12, pady=(8, 0), sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.items = tk.Text(details, state="disabled", wrap="word", height=5, width=20, font="TkDefaultFont")
        self.items.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(details, orient="vertical", command=self.items.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.items.configure(yscrollcommand=bar.set)

        bottom = ttk.Frame(self, padding=12)
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="正在读取整理历史…")
        ttk.Label(bottom, textvariable=self.status, wraplength=360).grid(row=0, column=0, sticky="w")
        self.undo = ttk.Button(bottom, text="撤销所选批次…", command=self.confirm_undo, state="disabled")
        self.undo.grid(row=0, column=1, padx=6)
        ttk.Button(bottom, text="关闭", command=self.close).grid(row=0, column=2)
        self.read(self.service.report_history, self.loaded)

    def read(self, action, completed):
        # Only the Tk thread interacts with widgets. Rapid selections coalesce to the latest job.
        if self.timer is not None:
            self.after_cancel(self.timer)
        if self.read_job is not None:
            self.read_job.cancel()
        self.read_job = self.reader.submit(action)

        def check():
            self.timer = None
            if not self.read_job.done():
                self.timer = self.after(60, check)
                return
            try:
                result = self.read_job.result()
            except (ValueError, OSError, RuntimeError) as error:
                self.status.set(f"报告读取失败：{error}")
                return
            completed(result)

        self.timer = self.after(20, check)

    def loaded(self, history):
        for record in history["reports"]:
            key = record["report_id"]
            self.records[key] = record
            self.rows.insert("", "end", iid=key, values=(
                record["created_at"], record["summary"]["moved"], record["summary"]["skipped"], record["status_label"]))
        hints = [f"{len(self.records)} 个整理批次" if self.records else "此目录尚无可用报告"]
        if history["invalid_count"]:
            hints.append(f"忽略了 {history['invalid_count']} 份无效报告")
        if history["truncated"]:
            hints.append("仅显示最近批次")
        if history.get("warning"):
            hints.append(history["warning"])
        self.status.set(" · ".join(hints))
        if self.records:
            self.rows.selection_set(next(iter(self.records)))

    def set_items(self, text):
        self.items.configure(state="normal")
        self.items.delete("1.0", "end")
        self.items.insert("1.0", text.encode("utf-8", errors="backslashreplace").decode("utf-8"))
        self.items.configure(state="disabled")

    def select(self):
        selected = self.rows.selection()
        self.undo.state(["disabled"])
        if not selected:
            self.set_items("")
            return
        key = selected[0]
        self.set_items("正在读取报告条目…")

        def show(report):
            if self.rows.selection() != (key,):
                return
            lines = [f"{item['source_path']}\n    → {item['actual_target_path'] or item['target_path']}"
                     for item in report["items"]]
            if report["items_truncated"]:
                lines.append(f"报告共 {report['item_count']} 项，仅展示前 {len(report['items'])} 项。")
            self.set_items("\n".join(lines) or "当前报告没有文件条目。")
            if report["can_undo"]:
                self.undo.state(["!disabled"])

        self.read(lambda: self.service.report_summary(key), show)

    def confirm_undo(self):
        if self.undo.instate(["disabled"]) or not self.rows.selection():
            return
        record = self.records[self.rows.selection()[0]]
        if not messagebox.askyesno("确认撤销本批次", f"将按 {record['created_at']} 的完整报告恢复 "
                                   f"{record['summary']['moved']} 个已移动文件。", parent=self, default="no"):
            return
        try:
            self.service.start_undo(record["report_id"])
        except (ValueError, OSError, RuntimeError) as error:
            messagebox.showerror("撤销失败", str(error), parent=self)
            return
        self.close()
        self.refresh()

    def close(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.reader.shutdown(wait=False, cancel_futures=True)
        self.destroy()
