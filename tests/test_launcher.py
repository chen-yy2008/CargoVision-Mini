"""启动器配置、原生 Tk 交互与设备子进程回归；不访问用户相机/偏好。"""

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from tests.camera_fixtures import make_camera, utf8_environment

import cv2
import numpy as np

from calibration import create_plane_calibration, save_calibration
from camera_utils import save_camera_preference
from config import OUTPUT_DIR, PROJECT_DIR
import launcher
from launcher_config import (DEFAULTS, build_command, calibration_state, camera_key,
                             initial_settings, save_settings, validate_settings)
import launcher_worker
from scripts.make_calibration_demo import make_demo_calibration
from tests.calibration_fixtures import synthetic_intrinsics


class LauncherConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=OUTPUT_DIR)
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.path, self.camera = self.project / "启动器.json", self.project / "设备.json"
        self.settings = {**DEFAULTS, "camera_index": 2}

    def plane(self):
        path = self.project / "中文 目录" / "平面.json"
        save_calibration(path, make_demo_calibration())
        return path

    def test_initial_default_never_guesses_a_camera(self):
        settings, preference, errors = initial_settings(self.path, self.camera)
        self.assertIsNone(settings["camera_index"])
        self.assertEqual((settings["width"], settings["height"]), (640, 480))
        self.assertIsNone(preference)
        self.assertEqual(errors, [])

    def test_adopts_successful_device_but_not_higher_resolution(self):
        save_camera_preference(self.camera, 3, {"width": 1280, "height": 720, "backend": "DSHOW"})
        settings, preference, errors = initial_settings(self.path, self.camera)
        self.assertEqual(settings["camera_index"], 3)
        self.assertEqual((settings["width"], settings["height"]), (640, 480))
        self.assertEqual(preference["capture_size"], {"width": 1280, "height": 720})
        self.assertEqual(errors, [])

    def test_existing_480p_format_preferences_are_preserved(self):
        save_camera_preference(self.camera, 2, {"width": 640, "height": 480, "backend": "DSHOW",
                                               "requested_fourcc": "MJPG", "requested_fps": 30})
        settings, _, _ = initial_settings(self.path, self.camera)
        self.assertEqual((settings["fourcc"], settings["fps"]), ("mjpg", 30))

    def test_valid_settings_roundtrip_and_no_persisted_confirmation(self):
        self.settings["calibration_path"] = str(self.plane())
        save_settings(self.path, self.settings)
        restored, _, errors = initial_settings(self.path, self.camera)
        self.assertEqual(restored, self.settings)
        self.assertEqual(errors, [])
        self.assertNotIn("confirmed", json.loads(self.path.read_text(encoding="utf-8")))

    def test_corrupt_file_is_retained_and_error_is_explicit(self):
        self.path.write_bytes(b"broken")
        self.camera.write_bytes(b"broken")
        _, _, errors = initial_settings(self.path, self.camera)
        self.assertEqual(len(errors), 2)
        self.assertEqual(self.path.read_bytes(), b"broken")
        self.assertEqual(self.camera.read_bytes(), b"broken")

    def test_invalid_values_fail_without_writing(self):
        for field, value in (("camera_index", True), ("width", 0), ("min_area", 0), ("fps", float("nan")),
                             ("width_mm", float("inf")), ("height_mm", -3), ("backend", "bad"), ("version", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                save_settings(self.path, {**self.settings, field: value})
        self.assertFalse(self.path.exists())

    def test_atomic_save_failure_keeps_old_configuration(self):
        save_settings(self.path, self.settings)
        before = self.path.read_bytes()
        with patch.object(Path, "replace", side_effect=PermissionError("read-only")), self.assertRaises(PermissionError):
            save_settings(self.path, {**self.settings, "min_area": 800})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.project.glob("*.tmp")), [])

    def test_cli_new_device_overrides_stale_launcher_device(self):
        save_settings(self.path, {**self.settings, "width": 1280, "height": 720})
        save_camera_preference(self.camera, 4, {"width": 640, "height": 480, "backend": "MSMF"})
        settings, _, _ = initial_settings(self.path, self.camera)
        self.assertEqual((settings["camera_index"], settings["backend"], settings["width"]), (4, "msmf", 640))

    def test_calibrated_command_requires_session_confirmation(self):
        self.settings["calibration_path"] = str(self.plane())
        with self.assertRaisesRegex(ValueError, "先确认"):
            build_command(self.settings, "detect", "python.exe", self.project)
        state = calibration_state(self.settings, self.project)
        command = build_command(self.settings, "detect", "python.exe", self.project, confirmed=state["signature"])
        self.assertEqual(command[command.index("--calibration") + 1], self.settings["calibration_path"])
        self.assertEqual(command[command.index("--width") + 1], "640")
        self.assertEqual(command[command.index("--min-area") + 1], "300")

    def test_changed_file_revokes_existing_confirmation(self):
        path = self.plane()
        self.settings["calibration_path"] = str(path)
        token = calibration_state(self.settings)["signature"]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["id"] = "changed-plane"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "先确认"):
            build_command(self.settings, "detect", "python.exe", confirmed=token)

    def test_size_mismatch_and_missing_file_do_not_silently_drop_mm(self):
        self.settings["calibration_path"] = str(self.plane())
        with self.assertRaisesRegex(ValueError, "分辨率"):
            calibration_state({**self.settings, "width": 1280, "height": 720})
        self.settings["calibration_path"] = str(self.project / "missing.json")
        with self.assertRaises(OSError):
            build_command(self.settings, "detect", "python.exe")

    def test_existing_undistorted_plane_requires_matching_intrinsics(self):
        camera = synthetic_intrinsics()
        reference = make_demo_calibration()
        plane = create_plane_calibration(reference["corners_px"], 290, 195, camera["image_size"], intrinsics=camera)
        plane_path, camera_path = self.project / "undistorted.json", self.project / "内参.json"
        save_calibration(plane_path, plane)
        save_calibration(camera_path, camera)
        self.settings["calibration_path"] = str(plane_path)
        with self.assertRaisesRegex(ValueError, "内参"):
            calibration_state(self.settings)
        self.settings["intrinsics_path"] = str(camera_path)
        self.assertEqual(calibration_state(self.settings)["plane"]["pixel_frame"], "undistorted")

    def test_plane_command_uses_measured_mm_and_safe_argv_paths(self):
        settings = {**self.settings, "width_mm": 123.5, "height_mm": 456.75, "fps": 30, "fourcc": "mjpg"}
        output = self.project / "含 空格 & 符号.json"
        command = build_command(settings, "plane", self.project / "python.exe", self.project, output)
        self.assertIn(str(output), command)
        self.assertEqual(command[command.index("--width-mm") + 1], "123.5")
        self.assertEqual(command[command.index("--width") + 1], "640")
        self.assertNotIn("--calibration", command)


class LauncherWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=OUTPUT_DIR)
        self.addCleanup(self.directory.cleanup)
        self.result = Path(self.directory.name) / "状态.json"
        self.settings = {**DEFAULTS, "camera_index": 2}

    def preview(self, key, read_ok=True, visible=1):
        cap = make_camera()
        cap.read.return_value = (read_ok, np.zeros((480, 640, 3), np.uint8) if read_ok else None)
        with patch("launcher_worker.open_camera", return_value=cap), patch("launcher_worker.cv2.namedWindow"), \
                patch("launcher_worker.cv2.imshow"), patch("launcher_worker.cv2.waitKey", return_value=key), \
                patch("launcher_worker.cv2.getWindowProperty", return_value=visible), patch("launcher_worker.cv2.destroyAllWindows"), \
                redirect_stdout(io.StringIO()):
            try:
                code = launcher_worker.preview_camera(self.settings, self.result)
            finally:
                cap.release.assert_called_once()
        return code

    def test_confirm_reports_actual_capture_dimensions(self):
        self.assertEqual(self.preview(ord("c")), 0)
        data = json.loads(self.result.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "confirmed")
        self.assertEqual((data["info"]["width"], data["info"]["height"]), (640, 480))

    def test_cancel_or_window_close_does_not_confirm(self):
        for key, visible in ((ord("q"), 1), (27, 1), (ord("c"), 0)):
            self.preview(key, visible=visible)
            self.assertEqual(json.loads(self.result.read_text(encoding="utf-8"))["status"], "cancelled")

    def test_frame_failure_always_releases(self):
        with self.assertRaisesRegex(RuntimeError, "读取失败"):
            self.preview(0, read_ok=False)

    def test_close_between_window_query_and_draw_is_cancelled(self):
        cap = make_camera()
        cap.read.return_value = (True, np.zeros((480, 640, 3), np.uint8))
        with patch("launcher_worker.open_camera", return_value=cap), patch("launcher_worker.cv2.namedWindow"), \
                patch("launcher_worker.cv2.imshow", side_effect=cv2.error("window closed")), \
                patch("launcher_worker.cv2.getWindowProperty", side_effect=cv2.error("window closed")), \
                patch("launcher_worker.cv2.destroyAllWindows"), redirect_stdout(io.StringIO()):
            self.assertEqual(launcher_worker.preview_camera(self.settings, self.result), 0)
        cap.release.assert_called_once()
        self.assertEqual(json.loads(self.result.read_text(encoding="utf-8"))["status"], "cancelled")

    def test_scan_reports_devices_without_saving_preference(self):
        with patch("launcher_worker.list_cameras", return_value=[{"index": 2}]):
            self.assertEqual(launcher_worker.main(["scan", "unused", str(self.result)]), 0)
        self.assertEqual(json.loads(self.result.read_text(encoding="utf-8"))["devices"], [{"index": 2}])

    def test_worker_error_has_chinese_diagnostic_and_failed_status(self):
        request = Path(self.directory.name) / "request.json"
        request.write_text(json.dumps(self.settings), encoding="utf-8")
        with patch("launcher_worker.open_camera", side_effect=RuntimeError("设备已断开")), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(launcher_worker.main(["preview", str(request), str(self.result)]), 1)
        self.assertIn("摄像头操作失败", output.getvalue())
        self.assertEqual(json.loads(self.result.read_text(encoding="utf-8"))["status"], "error")


class LauncherGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=OUTPUT_DIR)
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.camera, self.settings_path = self.folder / "camera.json", self.folder / "launcher.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.root_destroyed = False
        self.root.bind("<Destroy>", self.record_destroy)
        self.addCleanup(self.destroy)
        self.app = launcher.Launcher(self.root, self.settings_path, self.camera)
        # ttk 的主题初始化由 C 层空闲事件调度，不在 after info 中。
        # 根窗口存活时完成初始化，避免下一例 update() 处理已销毁应用的事件。
        self.root.update_idletasks()

    def record_destroy(self, event):
        if event.widget is self.root:
            self.root_destroyed = True

    def destroy(self):
        # 用 Destroy 事件记录实际生命周期，不查询已销毁的 Tk，也不吞 TclError。
        if self.root_destroyed:
            return
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.update_idletasks()
        self.root.destroy()

    def select_camera(self):
        self.app.settings.update(camera_index=2, backend="dshow")
        self.app.verified_camera = camera_key(self.app.settings)

    def fake_job(self, action="detect", **extras):
        process = MagicMock(returncode=0)
        process.poll.return_value = 0
        return {"action": action, "process": process, "settings": deepcopy(self.app.settings),
                "preference_before": None, **extras}

    def test_empty_state_is_pixel_only_and_cannot_open_unknown_camera(self):
        self.assertIn("仅输出像素", self.app.calibration_label.get())
        with patch("launcher.subprocess.Popen") as spawn, self.assertRaisesRegex(ValueError, "尚未确认"):
            self.app.detect()
        spawn.assert_not_called()

    def test_parameter_dialog_saves_chinese_path_and_restores_next_launch(self):
        self.app.show_settings()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        frame = dialog.winfo_children()[0]
        for row, value in ((0, "2"), (6, "777"), (7, "123.5"), (8, "456.75")):
            entry = next(w for w in frame.grid_slaves(row=row, column=1))
            entry.delete(0, "end")
            entry.insert(0, value)
        buttons = next(w for w in frame.winfo_children() if isinstance(w, launcher.ttk.Frame))
        next(w for w in buttons.winfo_children() if w.cget("text") == "保存设置").invoke()
        self.assertEqual(self.app.settings["min_area"], 777)
        restored, _, _ = initial_settings(self.settings_path, self.camera)
        self.assertEqual((restored["width_mm"], restored["height_mm"]), (123.5, 456.75))
        self.assertFalse(self.app.confirm_var.get())

    def test_valid_plane_can_be_launched_after_explicit_session_confirmation(self):
        self.select_camera()
        path = self.folder / "平面 文件.json"
        save_calibration(path, make_demo_calibration())
        self.app.save({**self.app.settings, "calibration_path": str(path)})
        with self.assertRaisesRegex(ValueError, "先确认"):
            self.app.detect()
        self.app.confirm_var.set(True)
        self.app.confirm_calibration()
        with patch.object(self.app, "start_process") as start:
            self.app.detect()
        argv = start.call_args.args[1]
        self.assertEqual(argv[argv.index("--calibration") + 1], str(path))
        self.assertIn("已现场确认", self.app.calibration_label.get())

    def test_external_plane_edit_clears_visible_confirmation(self):
        self.select_camera()
        path = self.folder / "plane.json"
        save_calibration(path, make_demo_calibration())
        self.app.settings["calibration_path"] = str(path)
        self.app.confirm_var.set(True)
        self.app.confirm_calibration()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["id"] = "changed"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "先确认"):
            self.app.detect()
        self.assertFalse(self.app.confirm_var.get())

    def test_failed_child_shows_error_and_does_not_write_settings(self):
        job = self.fake_job()
        job["process"].returncode = 1
        self.app.job = job
        with patch("launcher.messagebox.showerror") as error:
            self.app.finish(job)
        error.assert_called_once()
        self.assertFalse(self.settings_path.exists())
        self.assertIsNone(self.app.job)

    def test_preview_confirmation_saves_actual_camera_and_launcher_only_then(self):
        self.select_camera()
        result = self.folder / "result.json"
        result.write_text(json.dumps({"status": "confirmed", "info": {"width": 640, "height": 480, "backend": "MOCK"}}), encoding="utf-8")
        self.app.finish(self.fake_job("preview", result=result))
        self.assertTrue(self.camera.exists())
        self.assertTrue(self.settings_path.exists())
        self.assertIn("本次预览确认", self.app.actual.get())

    def test_cancelled_preview_keeps_preferences_unchanged(self):
        result = self.folder / "cancelled.json"
        result.write_text('{"status":"cancelled"}', encoding="utf-8")
        self.app.finish(self.fake_job("preview", result=result))
        self.assertFalse(self.camera.exists())
        self.assertFalse(self.settings_path.exists())

    def test_preview_mismatch_requires_acceptance(self):
        self.select_camera()
        result = self.folder / "result.json"
        result.write_text(json.dumps({"status": "confirmed", "info": {"width": 1280, "height": 720, "backend": "MOCK"}}), encoding="utf-8")
        with patch("launcher.messagebox.askokcancel", return_value=False):
            self.app.finish(self.fake_job("preview", result=result))
        self.assertFalse(self.camera.exists())
        self.assertEqual(self.app.settings["width"], 640)

    def test_scan_timeout_terminates_child_without_freezing_tk(self):
        log = self.folder / "empty.log"
        log.write_text("", encoding="utf-8")
        job = self.fake_job("scan", log=log, offset=0, started=0)
        job["process"].poll.return_value = None
        self.app.job = job
        with patch("launcher.monotonic", return_value=26):
            self.app.poll()
        job["process"].terminate.assert_called_once()
        self.assertTrue(job["cancelled"])
        self.app.job = None

    def test_launch_uses_argv_current_venv_and_single_process(self):
        self.select_camera()
        process = MagicMock()
        with patch("launcher.subprocess.Popen", return_value=process) as spawn:
            self.app.detect()
            self.assertEqual(spawn.call_args.args[0][0], str(PROJECT_DIR / ".venv" / "Scripts" / "python.exe"))
            self.assertNotIn("shell", spawn.call_args.kwargs)
            self.assertEqual(spawn.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8:strict")
            self.assertEqual(spawn.call_args.kwargs["cwd"], PROJECT_DIR)
            with self.assertRaisesRegex(ValueError, "已有程序"):
                self.app.detect()
        self.app.job = None

    def test_old_camera_preference_cannot_be_reported_as_new_capture(self):
        save_camera_preference(self.camera, 2, {"width": 640, "height": 480, "backend": "DSHOW"})
        self.select_camera()
        job = self.fake_job(preference_before=self.camera.stat().st_mtime_ns)
        before = self.app.actual.get()
        self.app.update_actual(job)
        self.assertEqual(self.app.actual.get(), before)

    def test_close_waits_and_kills_unresponsive_child(self):
        job = self.fake_job()
        job["process"].wait.side_effect = [subprocess.TimeoutExpired("worker", 2), 0]
        self.app.job = job
        with patch("launcher.messagebox.askokcancel", return_value=True):
            self.app.close()
        job["process"].terminate.assert_called_once()
        job["process"].kill.assert_called_once()

    def test_diagnostic_text_is_copyable(self):
        self.app.log("中文错误：摄像头已断开")
        self.app.copy_diagnostics()
        self.assertIn("摄像头已断开", self.root.clipboard_get())

    def test_early_close_is_destroyed_once_without_tcl_error(self):
        self.app.close()
        self.assertTrue(self.root_destroyed)
        with patch.object(self.root, "destroy") as destroy:
            self.destroy()
        destroy.assert_not_called()

    def test_cleanup_cancels_all_remaining_after_callbacks(self):
        callback = MagicMock()
        self.root.after(60000, callback)
        self.destroy()
        self.assertTrue(self.root_destroyed)
        self.assertEqual(self.root.tk.splitlist(self.root.tk.call("after", "info")), ())
        callback.assert_not_called()

    def test_log_chinese_split_at_64k_boundary_is_not_changed(self):
        text = "A" * 65535 + "摄像头 MOCK：第一行\n第二行中文。\n"
        path = self.folder / "split.log"
        path.write_bytes(text.encode("utf-8"))
        job = self.fake_job(log=path, offset=0)
        # 大块日志在此验证流处理，不让 Tk 对长行排版速度影响测试稳定性。
        output = io.StringIO()
        with patch.object(self.app, "log", side_effect=lambda text, **kwargs: output.write(text)):
            self.app.read_job_log(job)
            self.assertEqual(output.getvalue(), "A" * 65535)
            self.app.read_job_log(job, final=True)
        self.assertEqual(output.getvalue(), text)
        self.assertEqual(job["offset"], len(text.encode("utf-8")))
        self.assertEqual(path.read_bytes().decode("utf-8"), text)

    def test_log_bytewise_arrival_and_new_job_decoder_are_independent(self):
        text = "中文标准输出\n中文标准错误\n"
        for index in range(2):
            path = self.folder / f"bytewise{index}.log"
            path.write_bytes(b"")
            job = self.fake_job(log=path, offset=0)
            self.app.diagnostics.delete("1.0", "end")
            for value in text.encode("utf-8"):
                with path.open("ab") as stream:
                    stream.write(bytes([value]))
                self.app.read_job_log(job)
            self.app.read_job_log(job, final=True)
            self.assertEqual(self.app.diagnostics.get("1.0", "end-1c"), text)

    def test_failed_child_finish_drains_tail_without_cutting_or_repeating(self):
        text = "中文诊断" * 20000 + "\n"
        path = self.folder / "long.log"
        path.write_bytes(text.encode("utf-8"))
        job = self.fake_job(log=path, offset=0)
        job["process"].returncode = 1
        output = io.StringIO()
        with patch.object(self.app, "log", side_effect=lambda text, **kwargs: output.write(text)), \
                patch.object(self.app, "error") as error:
            self.app.read_job_log(job)
            self.app.finish(job)
        error.assert_called_once()
        self.assertEqual(output.getvalue(), text)
        self.assertTrue(job["log_complete"])

    def test_invalid_or_incomplete_utf8_is_rejected_without_replacement(self):
        for raw in (b"\xff", "中".encode("utf-8")[:2]):
            with self.subTest(raw=raw):
                path = self.folder / "invalid.log"
                path.write_bytes(raw)
                job = self.fake_job(log=path, offset=0)
                with self.assertRaises(UnicodeDecodeError):
                    self.app.read_job_log(job, final=True)
                self.assertTrue(job["log_error"])
                self.assertEqual(path.read_bytes(), raw)

    def test_bad_log_reports_once_and_does_not_claim_normal_exit(self):
        path = self.folder / "bad.log"
        path.write_bytes(b"\xff")
        job = self.fake_job(log=path, offset=0, started=time.monotonic())
        job["process"].poll.return_value = None
        self.app.job = job
        with patch.object(self.app, "error") as error:
            self.app.poll()
            self.app.poll()
            job["process"].poll.return_value = 0
            self.app.poll()
        error.assert_called_once()
        self.assertEqual(error.call_args.args[0], "日志编码错误")
        self.assertIn(str(path), error.call_args.args[1])
        self.assertIsNone(self.app.job)
        self.assertIn("编码错误", self.app.status.get())
        self.assertEqual(path.read_bytes(), b"\xff")

    def test_real_child_runs_synthetic_mm_workflow_and_returns_to_launcher(self):
        command = [str(self.app.python()), "-X", "utf8", str(PROJECT_DIR / "main.py"), "--image", str(PROJECT_DIR / "samples/demo.png"),
                   "--calibration", str(PROJECT_DIR / "samples/workplane_demo.json"), "--no-display"]
        self.app.start_process("detect", command, deepcopy(self.app.settings))
        deadline = time.monotonic() + 10
        while self.app.job and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        if self.app.job:
            self.app.job["process"].kill()
            self.app.job["process"].wait(timeout=2)
            self.fail("合成图片子进程超时")
        self.assertIn("4 个目标", self.app.diagnostics.get("1.0", "end"))
        self.assertIn("valid", self.app.diagnostics.get("1.0", "end"))
        self.assertFalse(self.camera.exists())
        self.assertFalse(self.settings_path.exists())


@unittest.skipUnless(os.name == "nt", "双击入口为 Windows CMD")
class BootstrapTests(unittest.TestCase):
    def test_missing_venv_has_explicit_chinese_error_and_no_install(self):
        with tempfile.TemporaryDirectory(dir=OUTPUT_DIR, prefix="中文 空格 ") as directory:
            path = Path(directory) / "Start_CargoVision.cmd"
            shutil.copyfile(PROJECT_DIR / "Start_CargoVision.cmd", path)
            process = subprocess.run(["cmd.exe", "/d", "/c", str(path)], input="\n", capture_output=True,
                                     encoding="utf-8", errors="strict", env=utf8_environment(), timeout=8)
            self.assertEqual(process.returncode, 1)
            self.assertIn("找不到项目", process.stdout)
            self.assertFalse((Path(directory) / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
