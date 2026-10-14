from __future__ import annotations

import argparse
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from lightnovel_selector.cli import (
    configure_stdio,
    main,
    parse_args,
    print_plan,
    run_cli,
)
from lightnovel_selector.models import ClassificationPlan


class TestCli(unittest.TestCase):
    def test_parse_args(self) -> None:
        args = parse_args(["myfolder", "--dry-run", "--quiet"])
        self.assertEqual(args.folder, "myfolder")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.quiet)
        self.assertFalse(args.recursive)
        self.assertFalse(args.sidecar)
        self.assertFalse(args.no_network)
        self.assertFalse(args.auto_rename)
        self.assertIsNone(args.undo_report)

        args_undo = parse_args(["--undo-report", "report.json"])
        self.assertEqual(args_undo.undo_report, "report.json")
        self.assertIsNone(args_undo.folder)

    def test_configure_stdio(self) -> None:
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        with patch.object(sys, "stdout", mock_stdout), patch.object(sys, "stderr", mock_stderr):
            configure_stdio()
            mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
            mock_stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_plan_empty(self, mock_stdout: StringIO) -> None:
        print_plan([])
        self.assertEqual(mock_stdout.getvalue().strip(), "没有找到可分类的小说文件。")

    @patch("sys.stdout", new_callable=StringIO)
    def test_print_plan_with_items(self, mock_stdout: StringIO) -> None:
        plan1 = ClassificationPlan(
            source_path=Path("source.txt"),
            series_name="series",
            target_dir=Path("target_dir"),
            target_path=Path("target.txt"),
            resolver_source="local",
            confidence=0.95,
            confidence_level="high",
            status="ready",
            classification_reason="Matched by rule",
            note="Will be moved",
        )
        plan2 = ClassificationPlan(
            source_path=Path("skip.txt"),
            series_name="series",
            target_dir=Path("target_dir"),
            target_path=Path("skip.txt"),
            resolver_source="local",
            confidence=0.5,
            confidence_level="low",
            status="skip_file_exists",
            classification_reason="Target file exists",
            note="",
        )
        print_plan([plan1, plan2])
        output = mock_stdout.getvalue()
        self.assertIn("MOVE\tsource.txt\t=>\ttarget_dir\\target.txt\t[local, 95% high, ", output)
        self.assertIn("SKIP\tskip.txt\t=>\ttarget_dir\\skip.txt\t[local, 50% low, ", output)

    @patch("lightnovel_selector.cli.run_cli")
    @patch("lightnovel_selector.cli.parse_args")
    def test_main_with_folder(self, mock_parse_args: MagicMock, mock_run_cli: MagicMock) -> None:
        mock_args = MagicMock()
        mock_args.sidecar = False
        mock_args.undo_report = None
        mock_args.folder = "myfolder"
        mock_parse_args.return_value = mock_args
        mock_run_cli.return_value = 0

        result = main(["myfolder"])

        mock_parse_args.assert_called_once_with(["myfolder"])
        mock_run_cli.assert_called_once_with(mock_args)
        self.assertEqual(result, 0)

    @patch("lightnovel_selector.cli.undo_classification_report")
    @patch("lightnovel_selector.cli.parse_args")
    def test_main_with_undo(self, mock_parse_args: MagicMock, mock_undo: MagicMock) -> None:
        mock_args = MagicMock()
        mock_args.sidecar = False
        mock_args.undo_report = "report.json"
        mock_args.quiet = True
        mock_args.folder = None
        mock_parse_args.return_value = mock_args
        mock_undo.return_value = (10, 2)

        result = main(["--undo-report", "report.json"])

        mock_parse_args.assert_called_once_with(["--undo-report", "report.json"])
        mock_undo.assert_called_once_with(Path("report.json"), progress=None)
        self.assertEqual(result, 0)

    @patch("sys.stderr", new_callable=StringIO)
    @patch("lightnovel_selector.cli.parse_args")
    def test_main_no_args(self, mock_parse_args: MagicMock, mock_stderr: StringIO) -> None:
        mock_args = MagicMock()
        mock_args.sidecar = False
        mock_args.undo_report = None
        mock_args.folder = None
        mock_parse_args.return_value = mock_args

        result = main([])

        mock_parse_args.assert_called_once_with([])
        self.assertEqual(result, 2)
        self.assertIn("未提供分类目录", mock_stderr.getvalue())

    @patch("lightnovel_selector.sidecar.SidecarServer")
    @patch("lightnovel_selector.cli.parse_args")
    def test_main_sidecar(self, mock_parse_args: MagicMock, mock_sidecar: MagicMock) -> None:
        mock_args = MagicMock()
        mock_args.sidecar = True
        mock_parse_args.return_value = mock_args

        mock_server = MagicMock()
        mock_server.serve_forever.return_value = 0
        mock_sidecar.return_value = mock_server

        result = main(["--sidecar"])

        mock_parse_args.assert_called_once_with(["--sidecar"])
        mock_sidecar.assert_called_once()
        mock_server.serve_forever.assert_called_once()
        self.assertEqual(result, 0)

    @patch("lightnovel_selector.cli.build_classification_plan")
    @patch("lightnovel_selector.cli.execute_classification_plan")
    @patch("lightnovel_selector.cli.PersistentScanCache")
    @patch("lightnovel_selector.cli.load_app_settings")
    def test_run_cli_dry_run(
        self,
        mock_load_settings: MagicMock,
        mock_scan_cache: MagicMock,
        mock_execute: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        args = argparse.Namespace(
            folder="myfolder",
            recursive=False,
            no_network=False,
            auto_rename=False,
            quiet=True,
            dry_run=True,
        )

        mock_settings = MagicMock()
        mock_settings.custom_rules = []
        mock_load_settings.return_value = mock_settings

        mock_cache_instance = MagicMock()
        mock_cache_instance.stats.reused_files = 0
        mock_cache_instance.stats.write_warning = None
        mock_scan_cache.return_value = mock_cache_instance

        mock_build.return_value = []

        result = run_cli(args)

        mock_load_settings.assert_called_once()
        mock_scan_cache.assert_called_once()
        mock_build.assert_called_once()
        mock_execute.assert_not_called()
        self.assertEqual(result, 0)

    @patch("lightnovel_selector.cli.build_classification_plan")
    @patch("lightnovel_selector.cli.execute_classification_plan")
    @patch("lightnovel_selector.cli.PersistentScanCache")
    @patch("lightnovel_selector.cli.load_app_settings")
    def test_run_cli_execute(
        self,
        mock_load_settings: MagicMock,
        mock_scan_cache: MagicMock,
        mock_execute: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        args = argparse.Namespace(
            folder="myfolder",
            recursive=False,
            no_network=False,
            auto_rename=False,
            quiet=False,
            dry_run=False,
        )

        mock_settings = MagicMock()
        mock_settings.custom_rules = []
        mock_load_settings.return_value = mock_settings

        mock_cache_instance = MagicMock()
        mock_cache_instance.stats.reused_files = 5
        mock_cache_instance.stats.write_warning = None
        mock_scan_cache.return_value = mock_cache_instance

        mock_plan = ClassificationPlan(
            source_path=Path("source.txt"),
            series_name="series",
            target_dir=Path("target_dir"),
            target_path=Path("target.txt"),
        )
        mock_build.return_value = [mock_plan]
        mock_execute.return_value = (1, 0)

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_cli(args)

            mock_load_settings.assert_called_once()
            mock_scan_cache.assert_called_once()
            mock_build.assert_called_once()
            mock_execute.assert_called_once()

            output = mock_stdout.getvalue()
            self.assertIn("增量扫描", output)
            self.assertIn("完成：移动 1 个文件", output)

        self.assertEqual(result, 0)
