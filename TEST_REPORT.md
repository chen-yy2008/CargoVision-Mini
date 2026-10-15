# V0.1 实际测试报告

测试日期：2026-10-15，Windows 工作区 `F:\奇妙小程序\机器人视觉`。

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
| unittest | **25 项通过，0 项失败，0 项跳过** |
| pip check | No broken requirements found |
| compileall | 全部源文件编译检查通过，退出码 0 |
| 无窗口图片 CLI | 退出码 0，4 个目标，PNG/JSON 写入 outputs/ |
| 不存在的图片 CLI | 退出码 1，明确显示「图片不存在或不是文件」 |
| 非法摄像头编号 CLI | --camera -1 退出码 2，明确提示编号必须大于等于 0；这是参数校验，不是硬件测试 |
| 原生窗口自动冒烟 | 使用真实 namedWindow / Trackbar / imshow；程序 waitKey 包装为等待 200 ms 后返回 q，图片模式退出码 0，无异常 |

单元测试 T01~T05：

- 三色检测、两个分离红色、每帧唯一 ID。
- 已知矩形/圆心 x/y 各允许 1 像素误差，当前样图结果为 `(110,130)`、`(290,130)`、`(480,140)`、`(180,340)`。
- 两端红色色相、可调面积、二值 Mask、零面积质心回退、原图不被标注修改。
- 噪点过滤、纯背景空列表、非法图像或面积拒绝。
- 实际写入并读回 PNG/JSON：图片像素与标注副本完全一致，JSON 与当前结果一致，字段齐全，无 confidence，时间带时区。
- 中文导出路径、连续保存不覆盖、尺寸不一致拒绝、JSON 写入失败清理半成品。
- 导出图已实际查看；修复相邻目标长标签重叠、同色中心十字不清楚的问题，修改后重新执行全部 25 项测试及无窗口图片导出，均通过。

T06 及窗口控制流程通过模拟对象验证：相机不可用、后端回退、帧读取失败、窗口初始化失败时资源释放；暂停/恢复/保存/退出；图片面积调整；Mask 选择；导出失败退出码和参数约束。

## 尚未验证

**没有实际打开或采集用户笔记本 / USB 摄像头。** 摄像头接口实现和故障分支已测试，真实设备的权限、驱动、占用、帧率、色彩及稳定性仍需用户在 Windows 本机验收。

原生窗口冒烟只证明创建/绘制/关闭路径没有抛出异常，不代表人工观察窗口成功，也没有验证真实键盘、鼠标拖动滑条或关闭按钮。PyCharm 本身也未实际操作，已提供解释器和运行配置说明。

按 README 的手工清单完成验收，再决定是否发布 v0.1.0。代码提交与推送用于审查，不表示摄像头验收通过；当前不创建正式 Tag 或 Release。

## Git 工作区检查

开发初始阶段已初始化本地 `main` 分支，初始化时无提交、Tag 或远程地址。已核对 `.venv/`、`.cache/` 和实验 PNG 被忽略，`outputs/.gitkeep` 未被忽略。初次初始化产生的空 Git 元数据属于沙箱账户，已确认无 refs / 对象 / 远程后保留到 `.cache/git-init-sandbox/`，并以用户账户重新初始化；当前普通 `git status --short` 可用。没有修改全局 Git 配置，也没有丢弃任何既有历史。后续按用户明确授权提交及推送代码用于审查，保持正式 Tag 和 Release 待定。
