# V0.1 实际测试报告

测试日期：2026-10-15，Windows 项目工作区。执行命令前进入包含 `main.py` 的项目根目录。

## 环境

- Python 3.12.14，64 位，项目独立 `.venv`。
- `opencv-python==4.12.0.88`（`cv2.__version__` 为 4.12.0）。
- `numpy==2.2.6`。
- 未修改原系统 `py` 登记、其他项目环境或用户 Python PATH。

## 已实际执行

```powershell
.\.venv\Scripts\python.exe scripts/make_demo.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q main.py config.py vision.py io_utils.py scripts tests
.\.venv\Scripts\python.exe main.py --image samples/demo.png --no-display
.\.venv\Scripts\python.exe main.py --image samples/missing.png --no-display
.\.venv\Scripts\python.exe main.py --camera -1
```

| 项目 | 实际结果 |
| --- | --- |
| 合成图生成 | 成功写入 640×480 的 samples/demo.png |
| unittest | **发布前复测 31 项通过，0 项失败，0 项跳过**；初版为 25 项 |
| pip check | No broken requirements found |
| compileall | 全部源文件编译检查通过，退出码 0 |
| 无窗口图片 CLI | 退出码 0，4 个目标，PNG/JSON 写入 outputs/ |
| 不存在的图片 CLI | 退出码 1，明确显示「图片不存在或不是文件」 |
| 非法摄像头编号 CLI | --camera -1 退出码 2，明确提示编号必须大于等于 0；这是参数校验，不是硬件测试 |
| 原生窗口自动冒烟 | 使用真实 namedWindow / Trackbar / imshow；程序 waitKey 包装为等待 200 ms 后返回 q，图片模式退出码 0，无异常 |
| 发布前原生窗口关闭回归 | 真实创建窗口后，分别在事件等待结束和滑条读取前调用 destroyWindow，图片模式均返回 0；未模拟实际摄像头或人工点击 |

单元测试 T01~T05：

- 三色检测、两个分离红色、每帧唯一 ID。
- 已知矩形/圆心 x/y 各允许 1 像素误差，当前样图结果为 `(110,130)`、`(290,130)`、`(480,140)`、`(180,340)`。
- 两端红色色相、可调面积、二值 Mask、零面积质心回退、原图不被标注修改。
- 噪点过滤、纯背景空列表、非法图像或面积拒绝。
- 实际写入并读回 PNG/JSON：图片像素与标注副本完全一致，JSON 与当前结果一致，字段齐全，无 confidence，时间带时区。
- 中文导出路径、连续保存不覆盖、尺寸不一致拒绝、JSON 写入失败清理半成品。
- 导出图已实际查看；修复相邻目标长标签重叠、同色中心十字不清楚的问题，修改后重新执行全部 25 项测试及无窗口图片导出，均通过。

T06 及窗口控制流程通过模拟对象验证：相机不可用、后端回退、帧读取失败、窗口初始化失败时资源释放；暂停/恢复/保存/退出；图片面积调整；Mask 选择；导出失败退出码和参数约束。

发布前新增 6 项回归测试：窗口可见性与查询异常；图片/摄像头模式关闭后正常退出；查询后关闭导致滑条、绘制、按键调用异常；窗口仍在时保留真实错误；关闭后不再读取新帧；清理窗口的异常不覆盖成功退出码。相关摄像头均为模拟对象，验证资源释放而非硬件兼容性。

## 实机验收与验证来源

**用户于 2026-10-15 明确确认：CargoVision V0.1 已通过 ChatGPT 离线代码审查和 Windows 上的全部实机测试。** 这是用户提供的验收结果，作为创建 v0.1.0 Tag 的依据。

Codex 执行了本报告中的自动测试、图片 CLI 和原生窗口自动检查，**没有直接采集用户笔记本 / USB 摄像头，也没有操作 PyCharm 或人工鼠标键盘**。发布前新增的窗口处理已完成模拟回归与原生窗口程序化关闭检查，不能将这些检查写成重新完成了实机摄像头实验。

后续更换电脑或摄像头时，可按 README 的手工清单再次验收。本次按用户授权创建并推送 v0.1.0 Tag，不单独创建 GitHub Release 页面。

## Git 工作区检查

开发初始阶段初始化了本地 `main` 分支，后续按用户授权提交并推送至 `chen-yy2008/CargoVision-Mini`。发布前已读取远程 main 与 Tag 状态，确认没有远程新提交或已存在的 v0.1.0 Tag。

已核对 `.venv/`、`.cache/`、`__pycache__/`、临时文件、审查 ZIP、实验 PNG 以及常见凭证路径被忽略；已跟踪的输出目录内容仅为 `outputs/.gitkeep`。没有修改全局 Git 配置，也没有丢弃任何既有历史。后续提交和 Tag 使用正常推送，不强制覆盖远程内容。
