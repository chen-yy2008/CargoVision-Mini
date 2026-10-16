# CargoVision 实际测试报告

## V0.2 开发版 — 2026-10-16

### 环境与实际执行

复用项目原有 Windows x64 `.venv`：Python 3.12.14、opencv-python 4.12.0.88（cv2 4.12.0）、NumPy 2.2.6；没有新增第三方依赖或修改其他项目。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py vision.py config.py io_utils.py calibration.py calibrate_plane.py calibrate_camera.py scripts tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe main.py --image samples/demo.png --no-display
.\.venv\Scripts\python.exe main.py --image samples/demo.png --calibration samples/workplane_demo.json --no-display
.\.venv\Scripts\python.exe calibrate_plane.py --inspect samples/workplane_demo.json
.\.venv\Scripts\python.exe scripts/evaluate_calibration.py --input samples/validation_example.csv --calibration samples/workplane_demo.json
.\.venv\Scripts\python.exe calibrate_camera.py --images camera_photos --cols 9 --rows 6 --square-mm 20
```

最后一条是对没有照片的目录执行的失败路径检查，预期退出码 1；真实操作应将棋盘格照片单独放进 camera_photos/chessboard，再按 README 执行。

| 验证项 | 实际结果与边界 |
| --- | --- |
| unittest | **74 项通过，0 失败，0 跳过**；保留初版 31 项并适配 JSON 0.2，新增 43 项 |
| compileall / pip check | 均通过；无依赖冲突 |
| 原有图片命令 | 4 个目标，uncalibrated，无 center_mm，PNG/JSON 保存成功 |
| 合成毫米图片命令 | 4 个目标且均在 ROI 内；中心约为 (45,40)、(135,40)、(230,45)、(80,145) mm；这些只是合成映射值 |
| 合成平面配置 inspect | 成功读取，输出 H、尺寸、四角、分辨率、原点、轴与 raw 状态 |
| 合成误差 CSV | 平均距离 3.333333 mm，最大 5 mm，RMSE 4.082483 mm，与手算一致；不代表相机精度 |
| 空棋盘格目录 | 明确提示至少需要 5 幅，退出码 1，没有创建真实相机参数 |
| 原生平面窗口程序化检查 | 真实创建 AUTOSIZE 窗口和注册鼠标回调，用程序输入四个合成点、S 保存，再读取验证；通过，不是人工点选或实物实验 |
| 原生毫米预览窗口检查 | 真实创建窗口、绘制标注并自动 Q 退出；通过，仅使用合成图 |
| 合成棋盘格照片 CLI 端到端 | 在临时目录生成 10 幅不同姿态的棋盘格 PNG，经实际角点检测、精修、求解、误差输出及 JSON 读取通过；非真实照片，临时文件已清理 |

### C01–C12 覆盖

- C01：四角对应的毫米数值和轴方向，误差容差 0.000001 mm，仅用于确定的合成数据。
- C02：合成透视映射的四个独立内部点，容差 0.0001 mm；它们没有参与计算 H，且不表示实物精度。
- C03：共线、近共线、重复、交叉、方向错误、区域过小、越界、非有限坐标、非法尺寸/类型均拒绝。
- C04/C05：raw/undistorted 平面与内参 JSON 中文路径读写，默认不覆盖；缺字段、坏版本、损坏矩阵、轴方向、时区、去畸变关联错误均拒绝。
- C06：图像尺寸改变时拒绝毫米结果，包括没有任何目标的图像，不静默缩放 H。
- C07/C08：无标定保留像素字段；区域外不含 center_mm，边界点有效，原检测列表不被改写。
- C09：同帧像素/毫米/标定 id、JSON 与 PNG 一致；导出 schema 0.2 和 image_pixel / workplane_mm 明确。
- C10：零畸变流程、分辨率匹配、原图/校正图不可混用、同 id 改参数的指纹拒绝；棋盘格检测、照片不足/重复/尺寸不一致、内参求解和实际重投影 RMSE。已知针孔参数投影角点求解测试误差小于 0.001 pixel，仅是数学测试。
- C11：三个独立点的 dx/dy/距离、均值/最大/RMSE 与手算一致；空/重复/NaN 数据、拟合角点与区域外真值有明确反馈；CSV/JSON 和输出防覆盖测试通过。
- C12：图片/模拟摄像头的暂停、保存、滑条、Mask、错误反馈、关闭窗口和资源释放保持；新增工具的冻结、缩放坐标、覆盖确认/取消/重选以及内参关联已测。

### 检查中发现并修复的问题

完整的合成棋盘格照片 CLI 检查发现，角点间距约 14~20 pixel 时，半径 11 的亚像素窗口可能跨到相邻角点，导致部分观测漂移。对同一合成数据比较后，使用 OpenCV 官方 calibrate.py 的半径 5；合成照片的总体重投影 RMSE 从约 1.73 降至约 0.31 pixel。已加入实际检测/精修/求解的回归测试，检查总体及最差视图误差小于 0.6 pixel，全部 74 项复测通过。

以上误差数值只描述这批人造图像和算法回归，没有实际相机、真实棋盘格、镜头畸变测量或毫米精度含义；程序报告逐图误差，不自动宣称某次标定足够精确。

### 待用户实测与版本管理

**V0.2 未实际采集真实摄像头、未取得真实 K/畸变、未在桌面完成四点标定，也未测得真实毫米误差。** Windows 实验步骤见 README 第 9–11 节。V0.1 用户已通过的实机验收仍保留为历史，不能替代新标定功能的验收。

代码继续在原 main 分支增量迭代，保留 v0.1.0；仅在测试通过后提交/推送开发代码，不创建 v0.2.0 Tag 或 Release。真实标定 JSON 和照片、实验输出、虚拟环境、缓存及审查 ZIP 默认不上传；公开的 samples 配置与测量例子明确标为合成数据。

---

# V0.1 历史测试报告

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
