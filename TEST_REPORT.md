# CargoVision 实际测试报告

## v0.4-A1：目标几何信息提取 — 2026-11-05

### 基线、范围与结果

- 本地工作区起始干净，本地及远程 main 均为 c31e7569f3d91305debcf3dadbf0774625b211f9；从该基线创建 feature/v0.4-geometry 开发分支，main 不改动。
- 原基线 163 项测试通过；新增 15 项离线几何测试后，**完整 unittest 为 178 项通过、0 失败、0 跳过**，不依赖真实摄像头。
- compileall、pip check、git diff --check 通过；通过 AST 比较确认原 Mask、质心和标注函数不变，检测函数移除新增元数据附件后与基线完全一致。
- 函数使用 OpenCV minAreaRect / boxPoints，仅在通过原面积筛选的对象上附加可选 geometry.rotated_rect_px；旋转矩形中心不替换原质心。
- 没有修改启动器、采集、显示、标定或毫米换算、导出函数、HSV 阈值、形态学常量和 requirements.txt；schema_version 仍为 0.2。

### 可重复验证证据

新增测试使用解析的正弦/余弦矩形点和合成 BGR 图像；期望值不使用 minAreaRect/boxPoints 自身构造，不依赖观察图片。原导出测试的精确字段集合仅扩展 geometry 这一新增字段，旧字段仍逐项要求保留；另测不含 geometry 的旧对象仍能原样导出。

| 项目 | 自动验证内容 |
| --- | --- |
| 水平矩形 | 边界 (40,70)→(200,130)，长160/短60 pixel，中心(120,100)，方向0°，四角明确匹配 |
| 旋转矩形 | -80/-35/-5/25/60/89/90/110/170° 样本；边长按栅格化误差容差验证，方向统一 [-90°,90°)，90→-90、110→-70 |
| 浮点中心 | 非整数中心 (100.25,75.5) 保留浮点精度，不四舍五入成旧质心 |
| 方向可靠性 | 圆形、104×100 的近方形在多个角度下为 false/null；长短边109/100为false，110/100及111/100为true |
| 四角 | 图像顺时针有向面积为正，首点为(y,x)最小；循环移位/反向输入不改变顺序；内置样本在画面内，边界三角形的外接矩形不被错误裁切 |
| 旧质心及面积 | L形目标外层质心(71,71)、矩形中心(90,90)分别保留；旧 bbox、轮廓面积和矩计算一致 |
| 空白与噪点 | 空白/默认过滤的小噪点仍无目标；调低面积可看到同一噪点及其无可靠方向几何 |
| 退化/非法值 | 空轮廓、点、直线、NaN、Infinity 输入不产生可选几何，不除零或导出非有限值 |
| 毫米兼容 | 合成平面中4个既有质心映射仍为(45,40)、(135,40)、(230,45)、(80,145) mm；id/color/bbox/area/geometry保留，mm_status仍为valid；仅为软件合成结果 |
| 实际 PNG/JSON | 通过 save_results 写临时文件并读回，geometry及旧字段匹配、无NaN/Infinity；无效角为null，旧对象没有geometry也可导出 |

本阶段只提交一个几何功能 Commit，不合并 main、不创建 PR/Tag/Release，不访问用户真实摄像头或改写设备/标定偏好。真实毫米精度与内参验收限制沿用下方 v0.2.0 记录；本次几何验证不扩大这些实机结论。

---

## v0.3 第一阶段：简易启动器（开发工作区，未发布）

### 软件实际检查

在 v0.2.0 最终提交 c526cc7 上增量开发，开始时工作区干净。环境为 Windows x64、Python 3.12.14、OpenCV 4.12.0、NumPy 2.2.6、Tk 8.6；没有增加第三方依赖。

| 检查 | 实际结果与边界 |
| --- | --- |
| 全部 unittest | **163 项通过，0 失败、0 跳过**；原有 129 项保留，新增启动器测试 34 项 |
| 配置与命令组装 | 默认 640×480、不猜相机、继承成功偏好、旧配置恢复、损坏文件明确报错、原子替换失败保留旧文件、参数单位/范围、路径空格中文、确认状态不持久化均通过 |
| 标定保护 | 复用 V0.2 文件/尺寸/raw/内参关联检查；缺文件/失配拒绝启动，文件变化撤销会话确认，不静默降级为像素模式 |
| 原生 Tk 测试 | 实际创建控件并操作参数表单、保存恢复、确认勾选、诊断复制、按钮状态、进程失败/取消/超时和退出回收；相机帧及多数子进程为模拟对象 |
| 实际子进程回归 | 从启动器进程管理启动原 main.py 的合成图片+合成平面无窗口流程，4 个目标、valid 状态，正常返回启动器；不是实机毫米精度结果 |
| Windows 双击入口正常路径 | 通过 cmd.exe 实际调用 Start_CargoVision.cmd，使用已有 .venv/pythonw 打开原生启动器，再程序化关闭；正式 camera.json / launcher.json 前后逐字节一致。窗口截图已查看，中文按钮、尺寸和标定状态可见 |
| 缺环境路径 | 在中文/空格临时目录复制入口、不提供 .venv，实际 cmd.exe 返回 1，显示中文缺环境提示，没有安装或创建虚拟环境 |
| 预览子进程 | 模拟帧验证 C 确认、Q/Esc/关闭取消、真实 shape 报告、读帧失败与关闭竞态时释放设备；模拟异常有中文诊断 |
| 编译/依赖/Git | compileall、pip check、git diff --check 通过；.gitattributes 为 CMD 固定 CRLF，避免克隆后中文批处理解析错误 |

实际执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q launcher.py launcher_config.py launcher_worker.py main.py camera_utils.py vision.py calibration.py scripts tests
.\.venv\Scripts\python.exe -m pip check
```

### 设备访问与尚未验收内容

本阶段曾尝试独立预览编号 2/DSHOW，设备打开失败，启动器显示中文失败提示且没有采用未确认的选择。**用户随后明确说明 USB 相机未插上，要求先不处理设备；此后不再探测或尝试打开相机。** 因此这个结果不视为 USB 功能故障，也不构成成功预览/实机验收；没有声称看到了 USB 实时画面、完成了人工 C 确认或真实毫米链路。

需要用户接入 USB 后验收：双击入口 → 选择实际 USB 编号并预览确认 → 640×480 实际尺寸 → 选择已有真实标定及配套内参（如适用）→ 确认现场条件 → 开始检测查看真实像素/毫米与 OUTSIDE ROI → P/S/Q/Mask/保存 → 退出重启恢复设置。还需检查拔出设备、错误诊断复制和退出后重新打开设备。v0.2.0 已记录的独立点定量精度、真实内参与畸变校正限制继续保留。

### 范围与开发中修复

新增 launcher.py、launcher_config.py、launcher_worker.py、Start_CargoVision.cmd 及测试、说明；原 main.py、vision.py、display.py、calibration.py、camera_utils.py、calibrate_plane.py、calibrate_camera.py、io_utils.py、requirements.txt 和历史测试均未修改。检测、标定数学、CLI、快捷键及 JSON schema 保持原样。

Windows 入口测试最初发现 LF 换行导致中文缺环境提示不能正确解析，已改为 CRLF 并设置专用 Git 属性；窗口关闭时的预览竞态按取消处理；本次实际尺寸只采用进程新写出的成功信息，避免把旧偏好误报为本次采集。所有软件回归通过。

设置保存在被忽略的 local_settings/，诊断与内部状态文件在被忽略的 .cache/launcher/；实际照片、标定及输出仍按既有规则留在本机。未迁移或删除用户实验数据。本阶段按用户授权提交/推送开发代码用于备份，真实 USB 启动器验收仍待完成；未创建正式 v0.3 Tag 或 Release，v0.2.0/v0.1.0 历史不变。

---

## v0.2.0 正式发布验收记录 — 2026-10-31

### 定位及验收来源

本版是**已完成基本实机功能验证的平面视觉定位原型**。用户已完成现有设备条件下的功能验收，并明确同意按早期原型标准结束 V0.2 阶段、创建正式 Tag/Release；独立点定量精度及真实内参校正仍是后续验证项目。本次发布不新增功能、不重构，软件代码保持提交 7e41c90 的实现。

以下实机结果来自用户本次明确反馈，Codex 未在发布收尾中重复执行实机验收。约 30 FPS 是用户报告的运行表现，不能据此认定驱动标称值、纯采集速率或传感器曝光帧率。

| 项目 | 验收结论与证据边界 |
| --- | --- |
| OV4689 USB 摄像头 | 640×480 正常稳定使用，用户报告约 30 FPS；不推广到其他模式或设备 |
| HSV 多目标颜色识别 | 用户确认正常 |
| 四点工作平面标定 | 用户已在真实画面完成标定 |
| 像素与毫米坐标 | 真实画面可输出，属于功能验证，不代表定量精度达标 |
| OUTSIDE ROI | 用户确认正常 |
| UI、保存、基本交互 | 用户确认可用 |
| 独立测量点定量统计 | 尚未完成；缺少精密固定装置，没有真实独立点的平均/最大误差或毫米 RMSE 结论 |
| 真实棋盘格内参/畸变校正 | 尚未验收；不得将合成棋盘格测试写成实机通过 |
| 1280×720 | 用户曾遇到黑屏，重新插拔后 640×480 恢复；不纳入稳定采集模式 |

不承诺特定毫米精度或工业级性能；不将工作平面坐标视为龙门架机械坐标、三维坐标或已验证抓取点。模式、镜头、安装及平面改变后重新验证或标定。

### 本次实际软件检查

- 开始时 main 工作区干净，最新实现提交为 7e41c90；远程 main 相同，v0.1.0 保留，远程无 v0.2.0 标签。
- `python -m unittest discover -s tests -q`：**129 项通过、0 失败、0 跳过**，本次发布收尾实际重新运行。
- `python -m compileall -q main.py camera_utils.py vision.py display.py config.py io_utils.py calibration.py calibrate_plane.py calibrate_camera.py scripts tests`：通过。
- `python -m pip check`：通过，无依赖冲突；依赖仍为 opencv-python 4.12.0.88、NumPy 2.2.6。
- 发布改动限 README.md、CHANGELOG.md、TEST_REPORT.md；不改检测、标定、采集、UI 或 JSON schema。
- .gitignore 检查：calibrations/、camera_photos/、local_settings/、outputs/ 的真实数据被忽略，保留受控目录下的 README/.gitkeep；.venv、缓存、日志及常见凭证路径被忽略。受控文件中没有已被忽略但仍跟踪的文件。
- 本次发布不上传实机照片、真实标定配置、个人设备偏好、原始探测报告或可执行包，仅发布源码及文档。

### 发布结论与历史记录说明

在上述边界下按用户授权发布 v0.2.0；附注 Tag 标记最终收尾提交，GitHub Release 概述功能、用户功能验收及限制。保留历史 v0.1.0，不重写提交或覆盖标签。

下文是发布前各阶段的开发记录，保留其当时的测试结果和未验收状态。历史上未确认物理身份的编号 2 所测 720p、其他尺寸或 FPS **不是 OV4689 的验收数据**；旧记录中“尚未真实平面标定”由本节用户验收更新，定量毫米精度和真实内参校正仍未验收。当前使用基线为用户确认的 640×480。

---

## USB 采集参数检查与配置 — 2026-10-31

### 软件回归

在已发布的 Windows 体验优化提交 `8ea3f2b` 上增量修改，开始时工作区干净。环境仍为 Python 3.12.14、OpenCV 4.12.0、NumPy 2.2.6，无新增依赖。

- `python -m unittest discover -s tests -q`：**129 项通过，0 失败、0 跳过**（保留原 106 项，新增 23 项）。
- compileall、pip check、git diff --check 通过。
- 新增回归覆盖旧偏好兼容、新格式/FPS 记忆与 CLI 优先级、auto 清除格式、非法/非有限参数、标定冲突前拒绝所有设置、属性与帧尺寸相矛盾、set=false 但真实尺寸正确、采集中尺寸变化、预热剔除、实测 FPS 与报告 FPS 分离、失败释放、进程超时、驱动日志隔离、损坏报告、无偏好不猜设备、数值报告及防覆盖。
- 通过 AST 对比确认 vision.py、display.py、calibration.py、io_utils.py、calibrate_camera.py、scripts/evaluate_calibration.py 与此次修改前完全一致；工作台、核心检测、导出 JSON、标定数学均未变。
- 实际运行未标定图片与合成平面图片 CLI，均识别 4 个目标，分别为 uncalibrated / valid；导出 PNG 保持 640×480、JSON schema 0.2。此处为合成图片回归。
- 原生窗口实际启动两次，各 8 次界面迭代，程序化 P/P/Q 暂停/恢复/退出，退出码均为 0。第一次指定编号 2/DSHOW/1280×720/auto；第二次不传参数，从临时配置恢复同一编号/后端/实际尺寸。没有保存摄像头照片，正式 local_settings/camera.json 前后逐字节一致。该检查不是人工键盘、长时间 UI 或真实 USB 身份验收。

### 当前设备访问与模式结果

正式本机偏好当前记录编号 0/DSHOW/640×480，本次尝试无法打开。另对可读取的编号 2 做检测，**未确认它对应的物理型号或 USB 身份**；下表不能代替用户 USB 实测，也不能用其他后端同编号推断同一物理设备。

使用 `scripts/probe_camera.py` 独立进程顺序尝试 2 后端 × 3 格式 × 5 尺寸，共 30 组，每组预热 3 帧、测量 2 秒、总时限 12 秒。未显式请求设备 FPS，未保存照片或修改偏好。

| 编号 / 后端 / 请求格式 | 请求尺寸 | 真实帧尺寸与测量结果 |
| --- | --- | --- |
| 2 / DSHOW / auto | 640×480 | 全部匹配，2 测量帧，约 1.000 read FPS |
| 2 / DSHOW / auto | 1280×720 | 全部匹配，60 测量帧，约 29.518 read FPS |
| 2 / DSHOW / auto | 1920×1080 | 全部匹配，2 测量帧，约 1.000 read FPS |
| 2 / DSHOW / auto | 2560×1440 | 全部匹配，2 测量帧，约 0.999 read FPS |
| 2 / DSHOW / auto | 3840×2160 | 全部匹配，2 测量帧，约 1.000 read FPS |
| 2 / DSHOW / MJPG 或 YUY2 | 上述各档 | FOURCC set 返回 false，预热读帧失败，无可报告帧率 |
| 2 / MSMF / auto、MJPG、YUY2 | 上述各档 | 打开失败，无尺寸/帧率数据；不能断言用户 USB 不支持 MSMF |

auto 组的宽高属性与 frame.shape 一致，FPS 与 FOURCC 属性未知；未将未知值替换为 30 或 MJPG。返回高分辨率数组不证明原生传感器像素或实际细节提升，低帧数也不适合下稳定性结论。

进一步预热 8 帧、测量 5 秒（20 秒总时限）：640×480 得到 5 帧、0.989 read FPS；1280×720 得到 124 帧、24.752 read FPS；1920×1080 得到 5 帧、0.992 read FPS。1280×720 复开再测 2 秒得到 60 帧、29.544 read FPS。**存在波动，不声称稳定 30 FPS。**

另对编号 2/DSHOW/1280×720/auto 显式请求 `--fps 30`，设备 set 确认、FPS 属性读回约 30.00003；预热 3 帧后测量 2 秒，60 帧、29.541 read FPS，真实尺寸全部匹配。此结果仍是短时纯采集吞吐率；FOURCC 仍未知，不能借此宣称已用 MJPG，亦不是原工作台处理 FPS。

### 故障与输出检查

实际构造编号 2/640×480、预热 60 帧、总时限 3 秒的探测，正确记录 timeout。随后立即重新打开编号 2/1280×720 读到 60 帧，验证超时子进程结束后可重新使用设备；timeout 不是不支持该尺寸的证明。正常、读帧失败、异常路径由 finally 释放，驱动阻塞路径由父进程结束该组并由系统回收句柄。

本次数值报告保留在 outputs/（已忽略，不上传）：

- `camera_probe_baseline_20261031.json`：编号 0/DSHOW 的失败记录。
- `camera_probe_index2_20261031.json`：另一个编号/后端的初步可读性检查。
- `camera_probe_matrix_20261031.json`：完整 30 组请求及实际结果。
- `camera_probe_confirm_20261031.json`：三种尺寸的 5 秒复测。
- `camera_probe_timeout_20261031.json`、`camera_probe_reopen_20261031.json`：超时与再次打开。
- `camera_probe_fps_request_20261031.json`：显式 30 FPS 请求与实测结果。

本机偏好、.venv、缓存、日志和 outputs 报告均被既有 .gitignore 排除，无需更改忽略规则；没有删除历史照片、标定或实验数据。本次提交仅包含采集配置、检测工具、测试与文档，不包含本机偏好或实验输出；不创建 Tag 或 Release。

### 候选模式与用户验收

本会话中可优先继续验证的候选为 **编号 2 / DSHOW / 1280×720 / auto**，可另比较 `--fps 30`；由于设备身份未确认，不能替用户把正式编号 0 改成 2，也不能称为用户 USB 的最终推荐模式。其他尺寸虽然返回了对应数组，当前吞吐率较低；MJPG/YUY2 未成功，不建议盲目强制使用。

用户需在真实 USB 所在 Windows 上核对画面/编号，执行 README 第 14 节工具，比较实际分辨率、read FPS、清晰度与长时间掉帧。选好模式后用 main.py 保存偏好，退出并分别在 PowerShell/PyCharm 无参数重启；检查 P/S/Q、Mask、窗口缩放和原尺寸保存。平面工具与识别使用相同设备/后端/宽高/格式/FPS 请求；更换模式后复核视野，重新做或验证内参、平面及独立毫米点，不沿用尺寸不匹配的旧标定。本次没有真实平面标定或毫米精度验收结论。

---

## Windows 使用体验优化 — 2026-10-31

### 实际执行与结果

继续使用原有 Windows x64 / Python 3.12.14 / OpenCV 4.12.0 / NumPy 2.2.6；没有新增第三方依赖。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py vision.py config.py camera_utils.py display.py calibration.py calibrate_plane.py calibrate_camera.py io_utils.py scripts tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe main.py --image samples/demo.png --no-display
.\.venv\Scripts\python.exe main.py --image samples/demo.png --calibration samples/workplane_demo.json --no-display
.\.venv\Scripts\python.exe main.py --list-cameras --scan-limit 3
```

| 项目 | 结果与边界 |
| --- | --- |
| unittest | **106 项通过，0 失败、0 跳过**；原有 74 项保留，新增 32 项设备/显示回归 |
| compileall / pip check | 通过；依赖无冲突 |
| 图片模式/合成毫米模式 | 均检测到 4 个目标，PNG 保留原始 640×480，JSON 保持 0.2；有效毫米点与原合成期望一致 |
| 原生窗口初始化/缩放 | 960×720、800×500、1000×650 各连续刷新 4 次，图像区域尺寸稳定，未随帧改变窗口大小；缩放由程序模拟，不是人工鼠标验收 |
| 原生关闭窗口 | 实际创建图像窗口后程序化关闭，主循环退出码 0 |
| 密集目标 | 实际生成并查看 60 个合成目标的预览；短编号避让、信息区分页，无逐目标 UNCALIBRATED |
| 实际设备探测 | 当前会话检测 0..2 时成功读到一个 DSHOW 设备，实际 640×480，驱动报告 FPS 未知；其他编号未能读取，不据此断言不存在 |
| 实际设备短时检查 | 同一可读索引两次启动，各 6 帧预览后自动 Q；第二次不传 --camera，从临时偏好恢复相同索引/后端/尺寸，退出码均为 0 |

实际设备检查没有保存摄像头照片，配置放在 `.cache` 下的临时目录并已清理，没有替用户改写正式 `local_settings/camera.json`。索引对应的物理型号/USB 身份未确认，也没有据此声称已完成全部实机交互或毫米精度验收。设备报告 FPS 未知时未伪造数字，循环 FPS 与驱动 FPS 分开。

### 专项回归覆盖

- 显式选择优先、本地偏好恢复、首次无偏好回退 0、保存中文路径、原子替换及失败保留旧配置、损坏配置明确拒绝、显式重新选择绕过损坏配置。
- 保存的设备/后端失败时不改用其他编号或后端；枚举必须实际读到帧，所有探测句柄释放；打开成功但读帧失败时可继续探测同索引的其他后端。
- 分辨率只按请求设置；设置前拒绝与标定冲突；检查实际帧尺寸，设备返回与请求不符时提示并记录实际值；故障路径释放句柄且不保存错误选择。
- 4:3、16:9、竖图等比布局，小屏初始尺寸，窗口初始化只调整一次，预览缩放不改源数组/对象/毫米值/JSON。
- 密集编号不越界、不相互覆盖，中心十字保护，极密时保留分页完整列表；像素/毫米/区域外状态、D 详细、[ ] 翻页和 +/- 1 px² 精调。
- 原有 P/S/Q/Esc、Mask、图片、内参、四点平面映射和导出测试继续通过。旧 Mask 选择测试改为隔离画布绘制验证输入 Mask，新增测试独立验证实际画布几何。

### 检查中修复

密集小目标测试首次发现：标签只按框边缘寻找位置时，中心保护区可能挡住所有候选。已把候选向十字保护区外移动，小目标采用较短十字，并在空间不足时使用列表而不是强行叠加文字。回归通过。

### 保持不变与待验收

已逐一比较 create_masks / detect_objects / contour_center 的 AST，确认与改动前一致；calibration.py、calibrate_camera.py、io_utils.py 和误差统计数学代码也与改动前一致（忽略换行风格）。相机选择/显示代码独立放在 camera_utils.py 和 display.py，JSON schema 不变。本机配置、测试日志、缓存和实验输出均被 Git 忽略；不删除旧数据、不创建正式 Tag / Release。本次提交范围为 Windows 使用体验优化的源码、测试与文档，不包含本机设备偏好和实验输出。

用户仍需确认：列表中的哪个编号确为 USB 摄像头、跨 PyCharm/PowerShell 重启偏好、拔出已选设备的行为、真实鼠标缩放、真实键盘/滑条、连续保存和长时间 FPS/稳定性。OpenCV 索引可能因插拔/重启而重排，当前实现无法永久绑定 Windows 物理设备，不能省略画面确认。V0.2 的真实标定/毫米精度仍需另行验收。

---

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
