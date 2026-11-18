"""Exercise real Tk controls and the real filesystem engine (run under xvfb-run on Linux)."""

import os
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from lightnovel_selector.application import ApplicationService
from linux.app import LibraryWindow, ReportHistory


class DesktopWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = Path(self.tmp.name) / "书库"
        self.library.mkdir()
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(Path(self.tmp.name) / "prefs")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.callback_errors = []
        self.root.report_callback_exception = lambda kind, error, trace: self.callback_errors.append(error)
        self.service = ApplicationService()
        self.app = LibraryWindow(self.root, self.service)
        with patch("linux.app.filedialog.askdirectory", return_value=str(self.library)):
            self.app.choose.invoke()
        self.assertTrue(self.service.settings.use_network)
        self.app.switches[2].invoke()
        self.assertFalse(self.service.settings.use_network)

    def wait_for(self, condition):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.root.update()
            if self.callback_errors:
                raise self.callback_errors[0]
            if condition():
                return
            time.sleep(0.01)
        self.fail(f"GUI did not reach requested state. {self.app.message.get()}")

    def test_preview_filter_correct_apply_and_undo_history(self):
        first = self.library / "青空物语 第1卷.txt"
        second = self.library / "落雪物语 第2卷.txt"
        first.write_text("volume one", encoding="utf-8")
        second.write_text("volume two", encoding="utf-8")
        self.app.scan_button.invoke()
        self.wait_for(lambda: len(self.app.tree.get_children()) == 2)
        self.assertTrue(first.exists() and second.exists())
        self.app.search.set("青空")
        self.wait_for(lambda: len(self.app.tree.get_children()) == 1)
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.root.update()
        with patch("linux.app.simpledialog.askstring", return_value="修正系列"):
            self.app.edit_button.invoke()
        self.assertIn("修正系列", self.app.detail_text.get("1.0", "end"))
        self.assertTrue(first.exists())
        with patch("linux.app.messagebox.askyesno", return_value=False):
            self.app.apply.invoke()
        self.assertTrue(first.exists() and second.exists())
        with patch("linux.app.messagebox.askyesno", return_value=True) as confirm:
            self.app.apply.invoke()
        self.assertIn("移动 2 个文件", confirm.call_args.args[1])
        self.wait_for(
            lambda: self.app.state["operation"]["state"] == "success" and self.app.state["operation"]["kind"] == "apply"
        )
        self.assertFalse(first.exists() or second.exists())
        self.assertEqual((self.library / "修正系列" / first.name).read_text(encoding="utf-8"), "volume one")
        self.app.history.invoke()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, ReportHistory))
        self.wait_for(lambda: bool(dialog.rows.get_children()) and not dialog.undo.instate(["disabled"]))
        self.assertIn(first.name, dialog.items.get("1.0", "end"))
        with patch("linux.history.messagebox.askyesno", return_value=True):
            dialog.undo.invoke()
        self.wait_for(
            lambda: self.app.state["operation"]["kind"] == "undo" and self.app.state["operation"]["state"] == "success"
        )
        self.assertEqual(first.read_text(encoding="utf-8"), "volume one")
        self.assertEqual(second.read_text(encoding="utf-8"), "volume two")
        self.assertEqual(self.app.tree.get_children(), ())


if __name__ == "__main__":
    unittest.main()
