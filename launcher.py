"""CargoVision 简易中文启动器；Tk 管交互，原检测/标定程序在单独进程运行。"""

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, time
import traceback
from uuid import uuid4

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from camera_utils import load_camera_preference, save_camera_preference
from config import CAMERA_PREFERENCE_PATH, PROJECT_DIR
from launcher_config import (SETTINGS_PATH, build_command, calibration_state, camera_key,
                             initial_settings, save_settings, validate_settings)


class Launcher:
    """一个窗口、一个子进程；不跨线程操作 Tk，不在事件回调里读取摄像头。"""

    def __init__(self, root, settings_path=SETTINGS_PATH, camera_path=CAMERA_PREFERENCE_PATH):
        self.root, self.settings_path, self.camera_path = root, Path(settings_path), Path(camera_path)
        self.settings, preference, errors = initial_settings(self.settings_path, self.camera_path)
        self.configuration_error = bool(errors)
        self.confirmed = None  # 现场确认绝不写进本机配置，下次启动重新确认。
        self.verified_camera = None
        self.last_actual = "本次尚未读取；没有上次成功记录。"
        if preference:
            size = preference["capture_size"]
            self.last_actual = f'上次成功：编号 {preference["camera_index"]} / {preference["backend"]} / {size["width"]}×{size["height"]} pixel；本次待读取。'
            if (self.settings["camera_index"] == preference["camera_index"] and
                    self.settings["width"] == size["width"] and self.settings["height"] == size["height"] and
                    self.settings["backend"] == (preference["backend"].lower() if preference["backend"] in ("DSHOW", "MSMF") else "auto") and
                    self.settings["fourcc"] == (preference.get("requested_fourcc") or "auto").lower() and
                    self.settings["fps"] == preference.get("requested_fps")):
                self.verified_camera = camera_key(self.settings)
        self.job = None
        self.root.title("CargoVision Mini — 简易启动器（v0.3 第一阶段）")
        self.root.geometry(f'820x{min(680, max(560, root.winfo_screenheight() - 120))}')
        self.root.minsize(650, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        panel = ttk.Frame(root, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="CargoVision Mini", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(panel, text="OV4689 已验收基线：640×480；编号不是永久 USB 身份，启动后请核对画面。", wraplength=750).pack(anchor="w", pady=(4, 12))
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        self.action_buttons = []
        for column, (label, callback) in enumerate((("打开实时检测", self.detect), ("选择摄像头", lambda: self.show_settings(True)),
                ("工作平面标定", self.calibrate), ("参数设置", self.show_settings))):
            button = ttk.Button(actions, text=label, command=callback)
            button.grid(row=0, column=column, padx=3, sticky="ew")
            actions.columnconfigure(column, weight=1)
            self.action_buttons.append(button)
        self.summary = tk.StringVar(root)
        self.actual = tk.StringVar(root, self.last_actual)
        self.calibration_label = tk.StringVar(root)
        self.status = tk.StringVar(root, "就绪。首次选择或更换采集设置后，请预览确认。")
        for variable in (self.summary, self.actual, self.calibration_label):
            ttk.Label(panel, textvariable=variable, wraplength=750, justify="left").pack(anchor="w", pady=(12, 0))
        self.confirm_var = tk.BooleanVar(root, False)
        self.confirm_check = ttk.Checkbutton(panel, text="我确认相机、镜头、采集条件和工作平面与所选标定一致（每次启动重新确认）",
                        variable=self.confirm_var, command=self.confirm_calibration)
        self.confirm_check.pack(anchor="w", pady=10)
        ttk.Label(panel, text="程序无法自动发现相机移动或工作平面改变；有变化请取消勾选并重新验证/标定。",
                  wraplength=750).pack(anchor="w")
        ttk.Separator(panel).pack(fill="x", pady=12)
        ttk.Label(panel, textvariable=self.status, wraplength=750).pack(anchor="w")
        bar = ttk.Frame(panel)
        bar.pack(fill="x", pady=8)
        self.stop_button = ttk.Button(bar, text="停止当前程序", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(bar, text="复制诊断信息", command=self.copy_diagnostics).pack(side="left", padx=8)
        ttk.Button(bar, text="退出", command=self.close).pack(side="right")
        self.diagnostics = ScrolledText(panel, height=9, wrap="word", font=("Consolas", 10))
        self.diagnostics.pack(fill="both", expand=True)
        self.refresh()
        for error in errors:
            self.log("配置错误：" + error)
        if errors:
            self.status.set("本机配置有错误，已保留原文件；请重新设置或预览确认后保存，暂不启动检测。")
        self.poll_id = self.root.after(200, self.poll)

    def log(self, text):
        """诊断区可选择/复制；历史完整子进程日志保留在被忽略的 .cache/launcher/。"""
        self.diagnostics.insert("end", text.rstrip() + "\n")
        self.diagnostics.see("end")

    def callback_error(self, kind, value, tb):
        self.error("操作失败", str(value), "".join(traceback.format_exception(kind, value, tb)))

    def error(self, title, detail, diagnostic=None):
        self.status.set(title + "：" + detail)
        self.log(diagnostic or self.status.get())
        messagebox.showerror(title, detail + "\n\n可点击“复制诊断信息”提供排查。", parent=self.root)

    def copy_diagnostics(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.diagnostics.get("1.0", "end"))
        self.status.set("诊断信息已复制。")

    def refresh(self):
        """文件校验状态与现场确认分开；内容变化或采集模式变化立即撤销会话确认。"""
        s = self.settings
        self.summary.set(f'请求：摄像头 {s["camera_index"] if s["camera_index"] is not None else "未选择"} / {s["backend"]} / '
                         f'{s["width"]}×{s["height"]} pixel；最小面积 {s["min_area"]} px²\n'
                         f'新标定的实测宽高：{s["width_mm"]:g}×{s["height_mm"]:g} mm（默认仅为 A4 示例）')
        self.actual.set(self.last_actual)
        try:
            state = calibration_state(s)
            self.confirm_check.configure(state="normal" if (state["plane"] or state["intrinsics"]) and not self.job else "disabled")
            if self.confirmed != state["signature"]:
                self.confirmed = None
                self.confirm_var.set(False)
            text = state["message"]
            if self.confirmed is not None:
                text = "已现场确认，实际帧仍由运行程序检查。" + text.replace("待现场确认", "已确认")
            if s["calibration_path"]:
                text += "\n文件：" + s["calibration_path"]
            self.calibration_label.set(text)
        except (OSError, ValueError) as exc:
            self.confirm_check.configure(state="disabled")
            self.confirmed = None
            self.confirm_var.set(False)
            self.calibration_label.set("标定不可用（不自动降为像素模式）：" + str(exc))

    def confirm_calibration(self):
        if self.confirm_var.get():
            self.confirmed = calibration_state(self.settings)["signature"]
        else:
            self.confirmed = None
        self.refresh()

    def save(self, candidate, check_files=True):
        candidate = validate_settings(candidate)
        if check_files:
            calibration_state(candidate)
        save_settings(self.settings_path, candidate)
        self.settings = candidate
        self.configuration_error = False
        self.refresh()
        self.status.set("本机设置已保存；采集请求以实际返回值为准。")

    def show_settings(self, camera_only=False):
        """简单参数表单；摄像头对话框额外支持编号扫描和先预览再确认。"""
        if self.job:
            raise ValueError("请先用 Q 退出或停止当前程序，再修改设置。")
        dialog = tk.Toplevel(self.root)
        dialog.title("选择摄像头" if camera_only else "参数设置")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        variables = {}
        fields = [("camera_index", "摄像头编号（OpenCV 索引）"), ("backend", "采集后端"),
                  ("width", "采集宽度（pixel）"), ("height", "采集高度（pixel）"),
                  ("fourcc", "采集格式（auto = 不设置）"), ("fps", "请求帧率（FPS，留空 = 不设置）")]
        if not camera_only:
            fields += [("min_area", "最小检测面积（px²）"), ("width_mm", "新标定实测宽度（mm）"),
                       ("height_mm", "新标定实测高度（mm）"), ("calibration_path", "平面标定文件（空 = 仅像素）"),
                       ("intrinsics_path", "相机内参文件（可选）")]
        for row, (key, label) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            variables[key] = tk.StringVar(dialog, "" if self.settings[key] is None else str(self.settings[key]))
            choices = ("auto", "dshow", "msmf") if key == "backend" else (("auto", "mjpg", "yuy2") if key == "fourcc" else None)
            if choices:
                widget = ttk.Combobox(frame, textvariable=variables[key], values=choices, state="readonly", width=42)
            else:
                widget = ttk.Entry(frame, textvariable=variables[key], width=45)
            widget.grid(row=row, column=1, sticky="ew", padx=8)
            if key.endswith("_path"):
                def browse(variable=variables[key]):
                    value = filedialog.askopenfilename(parent=dialog, initialdir=PROJECT_DIR / "calibrations",
                                                       filetypes=[("JSON 标定", "*.json"), ("所有文件", "*.*")])
                    if value:
                        variable.set(value)
                ttk.Button(frame, text="选择…", command=browse).grid(row=row, column=2)
        row = len(fields)
        ttk.Label(frame, text="640×480 为已验收基线；720p 曾黑屏。宽高 mm 请按实物填写。\n已有标定的物理宽高以标定文件为准，上述 mm 仅用于新标定。",
                  wraplength=630).grid(row=row, column=0, columnspan=3, sticky="w", pady=9)

        def collect():
            candidate = deepcopy(self.settings)
            try:
                for key, variable in variables.items():
                    value = variable.get().strip()
                    if key in ("camera_index", "width", "height", "min_area"):
                        candidate[key] = None if key == "camera_index" and not value else int(value)
                    elif key in ("width_mm", "height_mm", "fps"):
                        candidate[key] = None if key == "fps" and not value else float(value)
                    else:
                        candidate[key] = value
            except ValueError as exc:
                raise ValueError("编号、采集宽高和面积须填整数，实测毫米尺寸及帧率须填数值。") from exc
            return validate_settings(candidate)

        def save_and_close():
            candidate = collect()
            if (candidate["width"], candidate["height"]) != (640, 480) and not messagebox.askokcancel(
                    "确认采集模式", "当前分辨率不是已验收的 640×480，可能黑屏。标定须匹配并重新确认。仍保存吗？", parent=dialog):
                return
            self.save(candidate)
            dialog.destroy()

        def preview():
            if self.job:
                raise ValueError("正在扫描，请等待完成或取消当前操作后再预览。")
            candidate = collect()
            if candidate["camera_index"] is None:
                raise ValueError("请先填写或从列表选择摄像头编号。")
            dialog.destroy()
            self.start_worker("preview", candidate)
            self.status.set("预览窗口中核对画面，按 C 确认保存设备，Q/Esc 取消；这不是永久 USB 身份绑定。")

        buttons = ttk.Frame(frame)
        buttons.grid(row=row + 1, column=0, columnspan=3, sticky="ew")
        ttk.Button(buttons, text="预览并确认摄像头", command=preview).pack(side="left", padx=3)
        ttk.Button(buttons, text="保存设置", command=save_and_close).pack(side="left", padx=3)
        def cancel_dialog():
            if self.job and self.job["action"] == "scan":
                self.stop()
            dialog.destroy()
        ttk.Button(buttons, text="取消", command=cancel_dialog).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", cancel_dialog)
        dialog.bind("<Escape>", lambda _: cancel_dialog())
        devices = ttk.Combobox(frame, state="readonly", width=75)
        devices.grid(row=row + 2, column=0, columnspan=3, pady=8)
        entries = []

        def picked(_):
            if 0 <= devices.current() < len(entries):
                device = entries[devices.current()]
                variables["camera_index"].set(str(device["index"]))
                variables["backend"].set(device["backend"].lower() if device["backend"] in ("DSHOW", "MSMF") else "auto")
                # 换设备只选编号；请求尺寸保持显式字段，不把探测的默认尺寸偷偷套过来。
        devices.bind("<<ComboboxSelected>>", picked)

        def scanned(data):
            if dialog.winfo_exists():
                entries[:] = data["devices"]
                devices["values"] = [f'编号 {d["index"]} / {d["backend"]} / 探测实际 {d["width"]}×{d["height"]} pixel' for d in entries]
                if not entries:
                    self.status.set("未发现可读设备；也可能被占用或权限不足。可手填编号后预览。")
                else:
                    self.status.set("扫描完成；请从列表选择并预览核对画面，尚未更改相机偏好。")
        ttk.Button(frame, text="扫描编号 0～4（不改变选择）", command=lambda: self.start_worker("scan", collect(), scanned)).grid(row=row + 3, column=0, columnspan=3)

    def ensure_ready(self):
        if self.configuration_error:
            raise ValueError("本机配置有错误，请先在参数设置中重新保存或预览确认。")
        if self.verified_camera != camera_key(self.settings):
            raise ValueError("此摄像头/采集请求尚未确认，请点击“选择摄像头 → 预览并确认摄像头”。")

    def detect(self):
        self.refresh()
        self.ensure_ready()
        command = build_command(self.settings, "detect", self.python(), confirmed=self.confirmed)
        self.start_process("detect", command, deepcopy(self.settings))

    def calibrate(self):
        self.ensure_ready()
        output = filedialog.asksaveasfilename(parent=self.root, initialdir=PROJECT_DIR / "calibrations",
                    initialfile=f'workplane_{datetime.now():%Y%m%d_%H%M%S}.json', defaultextension=".json",
                    filetypes=[("平面标定 JSON", "*.json")])
        if not output:
            return
        command = build_command(self.settings, "plane", self.python(), output=output)
        self.start_process("plane", command, deepcopy(self.settings), output=output)
        self.status.set("标定窗口：F 冻结；TL→TR→BR→BL 点选四角；S 保存；Q/Esc 取消。")

    def python(self):
        path = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
        if not path.is_file():
            raise FileNotFoundError("找不到项目 .venv\\Scripts\\python.exe。请按 README 准备环境，不会自动安装。")
        return path

    def start_worker(self, action, settings, callback=None):
        directory = PROJECT_DIR / ".cache" / "launcher"
        directory.mkdir(parents=True, exist_ok=True)
        request, result = directory / f'{uuid4().hex}_request.json', directory / f'{uuid4().hex}_result.json'
        request.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        self.start_process(action, [str(self.python()), str(PROJECT_DIR / "launcher_worker.py"), action, str(request), str(result)],
                           settings, result=result, callback=callback)

    def start_process(self, action, command, settings, **extra):
        """shell=False、同一虚拟环境、单任务互斥；日志写文件避免 PIPE 填满死锁。"""
        if self.job:
            raise ValueError("已有程序运行，请先正常退出或停止。")
        directory = PROJECT_DIR / ".cache" / "launcher"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.log'
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        output_before = Path(extra["output"]).read_bytes() if extra.get("output") and Path(extra["output"]).exists() else None
        preference_before = self.camera_path.stat().st_mtime_ns if self.camera_path.exists() else None
        with path.open("wb") as stream:
            process = subprocess.Popen(command, cwd=PROJECT_DIR, stdout=stream, stderr=subprocess.STDOUT,
                                       env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.job = {"process": process, "action": action, "settings": deepcopy(settings), "log": path,
                    "offset": 0, "started": monotonic(), "output_before": output_before,
                    "preference_before": preference_before, **extra}
        if action in ("preview", "plane"):
            self.confirm_var.set(False)
            self.confirmed = None
        for button in self.action_buttons:
            button.configure(state="disabled")
        self.confirm_check.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("程序运行中；检测按 P/S/Q，预览按 C/Q，标定按 F/S/Q。")
        self.log(f"启动操作：{action}；诊断日志：{path}")

    def stop(self):
        if self.job:
            self.job["cancelled"] = True
            self.job["process"].terminate()
            self.job["stopping"] = monotonic()
            self.status.set("正在停止；正常使用建议在 OpenCV 窗口按 Q 释放设备。")

    def poll(self):
        """只用 after 轮询日志/进程；扫描和预览驱动卡住时可取消，Tk 保持响应。"""
        try:
            if self.job:
                job = self.job
                with job["log"].open("rb") as stream:
                    stream.seek(job["offset"])
                    content = stream.read(65536)
                    job["offset"] = stream.tell()
                if content:
                    self.log(content.decode("utf-8", errors="replace"))
                elapsed = monotonic() - job["started"]
                if job["action"] == "detect":
                    self.update_actual(job)
                if job["action"] in ("scan", "preview") and not job.get("stopping"):
                    heartbeat = job.get("result")
                    if heartbeat and heartbeat.exists():
                        # 状态文件每秒更新；mtime 使用墙钟，仅作超时保护，非帧率测量。
                        age = time() - heartbeat.stat().st_mtime
                    else:
                        age = elapsed
                    if (job["action"] == "scan" and elapsed > 25) or (job["action"] == "preview" and age > 15):
                        self.log("摄像头操作超时，请检查设备占用/权限和模式；已终止此操作。")
                        self.stop()
                if job.get("stopping") and monotonic() - job["stopping"] > 2 and job["process"].poll() is None:
                    job["process"].kill()
                if job["process"].poll() is not None:
                    self.finish(job)
        except (OSError, ValueError) as exc:
            self.error("状态读取失败", str(exc))
        self.poll_id = self.root.after(200, self.poll)

    def update_actual(self, job):
        """只采用本次运行新写出的成功偏好；旧记录不能冒充本次实际读取。"""
        if not self.camera_path.exists() or self.camera_path.stat().st_mtime_ns == job["preference_before"]:
            return
        preference = load_camera_preference(self.camera_path)
        if preference and preference["camera_index"] == job["settings"]["camera_index"]:
            size = preference["capture_size"]
            self.last_actual = f'本次检测实际：{size["width"]}×{size["height"]} pixel / {preference["backend"]}；设备编号仍可能重排。'
            self.actual.set(self.last_actual)

    def finish(self, job):
        self.job = None
        for button in self.action_buttons:
            button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.refresh()
        if job.get("cancelled"):
            self.status.set("当前程序已停止；未确认的设置和未保存标定不会被采用。")
            return
        if job["process"].returncode != 0:
            if job.get("log"):
                with job["log"].open("rb") as stream:
                    stream.seek(max(0, job["log"].stat().st_size - 65536))
                    self.log("程序末段诊断：\n" + stream.read().decode("utf-8", errors="replace"))
            self.error("程序未正常完成", "请查看下方中文诊断与驱动日志；不会自动切换相机或降级标定。")
            return
        action = job["action"]
        if action in ("scan", "preview"):
            data = json.loads(job["result"].read_text(encoding="utf-8"))
            if action == "scan":
                job["callback"](data)
                return
            if data["status"] != "confirmed":
                self.status.set("预览已取消，没有保存摄像头选择。")
                return
            info, candidate = data["info"], deepcopy(job["settings"])
            if (info["width"], info["height"]) != (candidate["width"], candidate["height"]):
                if not messagebox.askokcancel("实际尺寸与请求不同", f'实际返回 {info["width"]}×{info["height"]} pixel，是否按实际尺寸保存？标定需重新核对。', parent=self.root):
                    self.status.set("未采用不同尺寸的采集设置。")
                    return
            candidate.update(width=info["width"], height=info["height"])
            if info["backend"] in ("DSHOW", "MSMF"):
                candidate["backend"] = info["backend"].lower()
            info.update(requested_fourcc=None if candidate["fourcc"] == "auto" else candidate["fourcc"].upper(), requested_fps=candidate["fps"])
            save_camera_preference(self.camera_path, candidate["camera_index"], info)
            self.save(candidate, check_files=False)
            self.verified_camera = camera_key(candidate)
            self.last_actual = f'本次预览确认：{info["width"]}×{info["height"]} pixel / {info["backend"]}；设备编号仍可能重排。'
        elif action == "plane":
            path = Path(job["output"])
            if path.exists() and path.read_bytes() != job["output_before"]:
                candidate = deepcopy(self.settings)
                candidate["calibration_path"] = str(path)
                self.save(candidate)
                self.status.set("新平面标定已保存并选中。请确认现场条件后开始毫米检测。")
            else:
                self.status.set("标定已退出，没有新保存的标定文件。")
        else:
            self.update_actual(job)
            self.status.set("实时检测已退出。")
        self.refresh()

    def close(self):
        if self.job:
            if not messagebox.askokcancel("退出启动器", "当前程序仍运行。退出将停止它，未保存的数据会丢失。继续退出吗？", parent=self.root):
                return
            self.job["process"].terminate()
            try:
                self.job["process"].wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.job["process"].kill()
                self.job["process"].wait(timeout=2)
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    """双击入口的 Python 端；致命错误也给中文提示并保留本机诊断。"""
    root = tk.Tk()
    Launcher(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        diagnostic = traceback.format_exc()
        path = PROJECT_DIR / ".cache" / "launcher_startup_error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(diagnostic, encoding="utf-8")
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动器无法启动。请检查项目环境。\n诊断文件：{path}", "CargoVision 启动错误", 0x10)
        else:
            print(diagnostic, file=sys.stderr)
        raise SystemExit(1)
