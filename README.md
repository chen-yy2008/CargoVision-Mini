# CargoVision Mini（v0.4-A1 目标几何信息开发分支）

本分支以 main 的 `c31e756` 为基线，仅在原 HSV/轮廓检测结果上附加旋转矩形几何信息，约定见第 5 节。开发分支为 `feature/v0.4-geometry`，不合并 main，不创建正式 Tag 或 Release。

基线已包含**简易中文启动器**。已有项目 `.venv` 时，双击根目录的 **Start_CargoVision.cmd** 即可选择/预览摄像头、调整参数、选择标定并打开检测，不必修改 PyCharm 参数或 JSON。启动器使用标准库 Tkinter，不自动安装或修改环境；完整步骤见第 15 节。启动器尚待用户 Windows 实机验收，v0.4-A1 不修改其功能。

以下是 v0.2.0 视觉基线的定位与实机验收边界，启动器不改变这些检测与标定能力：

一个适合学习的 Python + OpenCV 桌面视觉项目，定位为**已完成基本实机功能验证的平面视觉定位原型**。保留红绿蓝多目标像素识别，提供四点工作平面毫米定位、独立棋盘格内参工具和独立验证点误差统计。v0.2.0 按用户授权以早期视觉原型标准结束 V0.2 阶段，保留历史 v0.1.0。

用户于 2026-10-31 确认：OV4689 USB 摄像头在 **640×480、约 30 FPS** 下正常稳定使用，HSV 多目标识别、真实四点平面标定、像素/毫米坐标输出、OUTSIDE ROI、UI、保存和基本交互通过验收。这些是用户本机反馈，Codex 未在本次发布收尾中重复实机验收；约 30 FPS 是用户报告的运行表现，不据此认定传感器曝光帧率。

**已知限制**：缺少精密固定装置，尚无独立测量点的定量精度统计；真实棋盘格内参和畸变校正尚未验收，不承诺特定毫米精度或工业级性能。1280×720 曾出现黑屏，重新插拔后 640×480 恢复正常；本版以已验收的 640×480 为使用基线，更高分辨率不作为已验证稳定模式。

**第一次真实标定可直接从第 9 节开始；棋盘格内参是第 11 节的可选进阶路径，不是四点标定的前置要求。**

## 1. 环境和首次安装

推荐 64 位 Python 3.11 / 3.12。当前已在 **Windows + Python 3.12.14 + OpenCV 4.12.0 + NumPy 2.2.6** 实测离线流程。只有 `opencv-python`、`numpy` 两个第三方依赖，测试使用标准库 `unittest`。

将仓库克隆或解压到自己选择的目录，建议文件夹名为 `CargoVision-Mini`。源码和子目录采用 ASCII 英文名；图片读写也支持 Windows 中文路径。

先在 PowerShell 或 PyCharm 终端中进入项目根目录（包含 `main.py`、`requirements.txt` 的文件夹），再执行以下命令。已有可用 `.venv` 时跳过创建步骤，**不要重复覆盖已有虚拟环境**。

```powershell
# 仅首次创建：先确认 py -3.12 能正常启动。
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果使用 Python 3.11，将 `py -3.12` 改为 `py -3.11`。如果没有 `py` 启动器，但 `python --version` 确认是已安装的 Python 3.11 / 3.12，可执行：

```powershell
python -m venv .venv
```

如果两个命令都不可用，先安装 64 位 Python 3.11 / 3.12，或在 PyCharm 中选择有效的基础解释器来创建 `.venv`。虚拟环境依赖基础解释器位置；更换电脑或移动解释器后应重新创建 `.venv` 并安装依赖，不要直接复制虚拟环境。

以下命令直接调用 `.venv` 的解释器，无需激活脚本，也无需修改 PowerShell 执行策略。首次安装需要网络；安装完成后，基础演示和测试均可离线运行。

## 2. 启动

日常使用优先双击 `Start_CargoVision.cmd`；首次缺少环境时按第 1 节准备，入口会明确提示并停止。下面所有命令行方式继续保留，供调试或离线处理使用。

```powershell
# 先列出可读取图像的编号/后端（默认检测 0..4）
.\.venv\Scripts\python.exe main.py --list-cameras

# 首次按列表选择相机。1 / dshow 仅为示例，请核对画面确实来自 USB 摄像头
.\.venv\Scripts\python.exe main.py --camera 1 --backend dshow

# 之后直接运行即可恢复上次成功选择，PyCharm 不填 Parameters 时同样生效
.\.venv\Scripts\python.exe main.py

# 本地图片，显示窗口；仓库已包含固定样图
.\.venv\Scripts\python.exe main.py --image samples/demo.png

# 无窗口检测并自动保存，便于无摄像头演示
.\.venv\Scripts\python.exe main.py --image samples/demo.png --no-display

# 合成毫米定位演示：配置明确标为 synthetic，不可用于真实摄像头
.\.venv\Scripts\python.exe main.py --image samples/demo.png --calibration samples/workplane_demo.json --no-display

# 调整初始最小轮廓面积；--save 只用于图片模式
.\.venv\Scripts\python.exe main.py --image samples/demo.png --min-area 500 --save

# 帮助、测试和依赖检查
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

如果 `.venv` 已激活，上述解释器路径可简写为 `python`，例如任务书中的 `python main.py --camera 0`。相对图片路径以当前工作目录为准，绝对路径可从任意目录运行。默认导出目录始终是项目根目录下的 `outputs/`。

## 3. PyCharm 设置

使用启动器不要求进入 PyCharm。以下设置仅用于源码学习和断点调试：

1. 用 PyCharm 打开当前项目文件夹。
2. 在项目 Python Interpreter 中添加本地已有解释器，选择项目根目录下的 `.venv\Scripts\python.exe`。
3. 创建 `main.py` 的运行配置，Working directory 设置为当前项目根目录。
4. 首次 Parameters 填 `--list-cameras` 检测，再填 `--camera N` 选择；成功后清空 Parameters 即可使用已保存的相机。图片模式仍填 `--image samples/demo.png`。
5. 操作按键前点击 OpenCV 图像窗口，使其获得焦点；不要在 PyCharm 编辑器中按 S/Q。

不需要安装其他 GUI 框架，也不要在同一个环境混装多个 `cv2` 包。

## 4. 窗口操作

| 操作 | 效果 |
| --- | --- |
| Q / Esc / 关闭图像窗口 | 退出，释放摄像头和窗口 |
| P | 摄像头模式暂停/恢复；暂停时仍可调参和保存 |
| S | 保存当前帧的彩色标注图及对应 JSON；可连续保存而不覆盖 |
| Min area 滑条 | 实时调整最小轮廓面积，单位 px²；0 按 1 处理 |
| + / = / - | 最小面积增加/减少 1 px²，便于精调 |
| D | 切换精简/详细目标列表；详细模式额外显示检测框尺寸和面积 |
| [ / ] | 目标列表上一页/下一页，目标较多时仍能查看全部像素与毫米坐标 |
| View 滑条 = 0 | 显示彩色原图及标注 |
| View = 1 / 2 / 3 | 显示红 / 绿 / 蓝 Mask，白色为被阈值选中的区域 |

面积滑条默认 0~5000，可用 `--area-max 20000` 扩展，也可用 `--min-area` 设置初值；旧的较大初值（最高 100000）仍接受，并自动扩展本次滑条范围。Mask 展示的是颜色分割及形态学处理后的结果，**尚未按最小面积删除白点**；小白点仍可能显示，但不会进入目标列表。即使预览 Mask，S 也保存对应帧的彩色标注图。图片模式不显示实时 FPS，也无需暂停。

画面上默认只画边框、黑白十字和 R#1 / G#2 / B#3 等短编号；对应的原始像素坐标、有效毫米坐标在右侧列表显示。未标定状态只在顶部出现一次。密集到无法放下编号时允许省略少量图内编号，完整目标仍在可翻页列表和 JSON 中，不强行叠加文字。D 只改变列表详细程度，不改变算法、数据或导出设置。

预览画布最大初始尺寸为 960×720，小屏幕会预留标题栏/滑条空间自动缩小；初始化后尊重手动窗口尺寸，原图居中等比例显示，空余区域补黑。窗口过窄时暂时收起右侧列表，放大即可查看。**预览缩放不参与检测/标定，导出 PNG 继续保持原始帧尺寸；完整坐标在未改 schema 的 JSON 中。** 保存成功/失败会在底部反馈，同时打印中文路径或错误原因。

## 5. 数据和已实现功能

- BGR → HSV，红色两个区间取并集，绿蓝各一个区间。
- 3×3 开/闭运算，外轮廓提取，按最小轮廓面积过滤；保留全部合格目标。
- 通过轮廓矩求质心，零面积退化轮廓回退到边界框中心。显示英文标签、像素坐标、目标数及摄像头循环 FPS。
- Windows 摄像头后端依次尝试 DirectShow / MSMF / 默认后端，打开失败或读取失败有中文提示。
- PNG 与 JSON 使用相同主干文件名，以微秒时间戳和随机后缀区分；独占创建，写入失败清理本次半成品。
- 读取、检测、标注、导出分离；标注不修改检测原图。暂停和保存均保留对应帧时间。

V0.2 JSON 使用 `schema_version: "0.2"`，保留 `coordinate_system: "image_pixel"`、`image_size`、`source`、带时区 `timestamp`、`objects`，以及目标的 `id/color/center_px/bbox_xywh/contour_area_px2`。空白图像的 `objects` 是 `[]`。新增字段：

- `pixel_frame`：`raw` 或 `undistorted`，说明 PNG、`center_px` 和检测框所属的同一图像空间。
- `workplane_coordinate_system: "workplane_mm"`：声明新增毫米字段的语义，不表示已经标定。
- `calibration.status`：无平面配置时为 `uncalibrated`；有效时为 `valid`，并记录标定 id、原点、轴、矩形尺寸、分辨率和内参关联指纹。
- 每个目标的 `mm_status`：`valid` / `uncalibrated` / `outside_roi` / `invalid_transform`。**只有 valid 时才附带 `center_mm: {"x": ..., "y": ...}`**。未标定或区域外不填零、不伪造毫米坐标。

### v0.4-A1 可选几何字段

每个已通过原面积筛选的目标，附加 `geometry.rotated_rect_px`。继续使用 `schema_version: "0.2"`，原 `id/color/center_px/bbox_xywh/contour_area_px2/center_mm/mm_status` 的字段名称、存在条件和计算方式不变。读取者应忽略不认识的可选嵌套字段；旧对象没有 geometry 时仍可正常导出。

以下仅为合成的水平矩形示例，不是实机测量：

```json
{
  "geometry": {
    "rotated_rect_px": {
      "center_px": {"x": 120.0, "y": 100.0},
      "long_side_px": 160.0,
      "short_side_px": 60.0,
      "aspect_ratio": 2.6666666666666665,
      "angle_deg": 0.0,
      "orientation_valid": true,
      "corners_px": [
        {"x": 40.0, "y": 70.0},
        {"x": 200.0, "y": 70.0},
        {"x": 200.0, "y": 130.0},
        {"x": 40.0, "y": 130.0}
      ]
    }
  }
}
```

| 字段 | 具体约定 |
| --- | --- |
| center_px | 旋转矩形中心，浮点 pixel；不是对象外层原有的轮廓矩质心，不用于替换毫米映射的输入 |
| long_side_px / short_side_px | minAreaRect 的两条边取大/小值，浮点 pixel；按几何长度计算，不是包含端点的 bbox 像素计数 |
| aspect_ratio | 长边 / 短边，无单位，非退化时 >= 1 |
| angle_deg | 由 boxPoints 的实际长边向量 atan2(dy,dx) 计算；以 +X 为零，X 向右、Y 向下，正值在图像中顺时针；无头尾长轴统一到 **[-90°,90°)**，竖直为 -90° |
| orientation_valid | 当 aspect_ratio **>= 1.10** 时为 true；阈值在 vision.py 独立常量 ORIENTATION_MIN_ASPECT_RATIO 管理。圆形、近正方形等低于阈值时为 false，angle_deg 为 **null** |
| corners_px | 四个浮点 {x,y}，按图像顺时针排列；起点是实际浮点坐标中 y 最小的顶点，y 相同时取 x 最小。它不是标定四角的 TL/TR/BR/BL 标签，也不保证跨帧角点身份连续 |

几何属于当前检测图像的 raw / undistorted 像素空间，和 `pixel_frame` 一致；本次不转换角点、边长或角度到毫米/机械坐标，不增加画面标注或操作。靠近图像边缘时，数学上的最小外接矩形可能伸出画面、包含负坐标；保留原浮点结果，不裁切角点以免破坏矩形。长宽比仅是方向稳定性的简单门槛，不是类别或精度置信度。空白/过滤掉的噪点仍无目标；退化或非有限几何不附加此字段，不输出 NaN/Infinity。

旧命令、像素检测和按键继续可用，读取 JSON 的外部程序需要识别显式升级的 0.2 schema。`v0.1.0` 历史版本仍保留 0.1 schema。CLI 发现配置损坏、分辨率不符或 raw/undistorted 混用时会报错退出，不静默缩放 H 或保存虚假毫米结果。

坐标原点位于图像左上角，x 向右、y 向下；单位为 pixel，面积单位为 pixel²。ID 仅在当前帧内唯一；不输出未经定义的 confidence。`timestamp` 是程序获取帧的本机时间，并非相机硬件曝光时间。

样图为 640×480：两个红色矩形、一个绿色矩形、一个蓝色圆和三个微小彩色噪点。默认参数应得到 **4 个目标**，中心为 `(110,130)`、`(290,130)`、`(480,140)`、`(180,340)`；测试允许 x/y 各误差不超过 1 像素。

`scripts/make_demo.py` 可重复生成同样的像素内容，已有 `samples/demo.png` 时会拒绝覆盖。需要重建时，先手动移走样图，然后执行：

```powershell
.\.venv\Scripts\python.exe scripts/make_demo.py
```

## 6. 项目结构

```text
CargoVision-Mini/
├── CargoVision_V0.1_Codex_Prompt.md  原始任务书
├── CargoVision_V0.2_Codex_Prompt.md  本版任务书
├── AGENTS.md                       长期工程约定
├── main.py                         CLI、摄像头循环、按键和简单窗口
├── camera_utils.py                 可读设备枚举、本机偏好、采集设置和实际信息
├── display.py                      等比显示、紧凑编号、分页目标信息区
├── config.py                       HSV、默认面积和路径
├── vision.py                       Mask、轮廓、质心和标注
├── io_utils.py                     中文路径图片读取、JSON 组装、成对导出
├── calibration.py                  H、ROI、内参/配置校验、去畸变和毫米附加
├── calibrate_plane.py              冻结画面、四角点选、覆盖确认和配置检查
├── calibrate_camera.py             棋盘格内参、亚像素角点和重投影误差
├── scripts/
│   ├── __init__.py
│   ├── make_demo.py                固定合成样图
│   ├── make_calibration_demo.py    固定合成平面配置
│   └── evaluate_calibration.py     独立验证点误差统计
├── samples/demo.png
├── samples/workplane_demo.json     明确标记的合成配置，可提交
├── samples/validation_example.csv  合成误差样例，需替换后才可评估实物
├── calibrations/                   真实标定配置，默认不上传
├── camera_photos/                  真实棋盘格照片，默认不上传
├── local_settings/camera.json      自动生成的本机相机偏好，默认不上传
├── tests/
│   ├── __init__.py
│   ├── test_vision.py              检测、几何和实际文件读写测试
│   ├── test_main.py                CLI 和模拟摄像头控制流程测试
│   ├── test_calibration.py         H、区域、配置和坐标空间验证
│   ├── test_calibration_tools.py   工具交互、内参和误差统计测试
│   ├── test_camera_utils.py        设备选择、配置持久化、分辨率与故障回归
│   ├── test_display.py             缩放、标签避让、分页和预览数据隔离
│   └── calibration_fixtures.py     固定合成内参/投影点，非设备参数
├── outputs/.gitkeep                实验输出被 Git 忽略
├── requirements.txt
├── README.md
├── LEARNING_GUIDE.md
├── TEST_REPORT.md
├── THIRD_PARTY_NOTICES.md
├── CHANGELOG.md
└── .gitignore
```

本机 `.venv/`、`.cache/`、`__pycache__/` 不进入版本管理。

## 7. 常见问题和局限

| 现象 | 排查方式 |
| --- | --- |
| python 找不到，或 py 指向不存在的路径 | 使用已有 `.venv\Scripts\python.exe`；首次创建时指定有效解释器完整路径 |
| 缺少 cv2 / numpy | 确认用项目解释器执行 `-m pip install -r requirements.txt` |
| OpenCV DLL 加载失败 | 确认是 64 位 Python，检查 Microsoft Visual C++ 运行库；Windows N 版本还需检查媒体组件 |
| 无法打开摄像头 | 检查编号、USB、Windows「隐私和安全性 → 相机」中的桌面应用权限，关闭相机/会议等占用程序 |
| 上次设备不可用 | 不会切换到另一个编号；执行 `--list-cameras`，核对画面后用 `--camera N` 重选 |
| 摄像头偏好损坏 | `--camera N` 显式重选会绕过损坏配置，成功读取后更新；也可手动移走 local_settings/camera.json |
| 帧读取失败 | 检查断连、设备忙和驱动，程序会释放资源并退出；重新启动尝试 |
| 图片不存在/解码失败 | 核对工作目录和文件名；确认文件是真实图片而非改扩展名的文本 |
| 目标漏检 | 先查看对应 Mask；调整光照、`config.py` 的 HSV 或降低最小面积，然后重新运行 |
| 目标粘连成一个 | 相同颜色且连通的区域可能合并；先分开物体，V0.1 不做遮挡分离 |
| 无法显示窗口 | 使用桌面版 `opencv-python`，不要使用 headless 包；无桌面时用图片 `--no-display` |
| 保存失败 | 检查磁盘空间和 `outputs/` 写权限；交互模式仍可继续运行并重试 |
| 标定四角无效 | 确认 TL→TR→BR→BL 顺序，矩形宽边大致向右、高边向下；避免重复、共线、交叉和过小区域 |
| 分辨率不匹配 | 用当前相机的实际采集尺寸重新标定；`--inspect` 查看记录，不缩放或手改 H |
| 去畸变内参不匹配 | 标定和检测同时启用同一份 `--intrinsics`；更换内参后重新制作平面配置 |
| OUTSIDE ROI | 质心不在标定四边形内，移回矩形区域；V0.2 不把外推坐标作为可靠输出 |
| 内参照片不足/角点失败 | 至少 5 幅有效且不同的视角，建议 15~25 幅；核对内角点数，保证完整清晰可见 |

HSV 阈值需要现场调整，强反光、阴影和低饱和度会影响结果。轮廓质心并非真实重心或可用抓取点；外轮廓方法不精确扣除内部孔洞。FPS 是包含读取、检测和显示等待的循环速率，不是设备额定帧率。强行结束进程或断电时不保证两文件成对写完。

**使用边界：本版毫米坐标属于固定相机下的同一工作平面，不是龙门架机械坐标、三维位置或已验证抓取点；没有机器人通信或电机控制。** `outputs/`、`calibrations/`、`camera_photos/` 可能包含个人画面和实际设备信息，默认不提交。不要将真实照片放进可公开的 `samples/`。

## 8. 验收与版本管理

已执行测试与未验证项见 [TEST_REPORT.md](TEST_REPORT.md)，源码学习见 [LEARNING_GUIDE.md](LEARNING_GUIDE.md)，第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

V0.1 的用户实机验收记录日期为 2026-10-15；v0.2.0 的基本功能验收与限制见本文开头和 TEST_REPORT.md。以下清单用于更换电脑、相机或后续迭代时重新验收，不代表每个项目都获得了新的定量测试结果：

- [ ] 打开实际摄像头，观察 FPS 和空白背景的 0 目标。
- [ ] 放入红、绿、蓝物体及两个分离的同色物体，核对框与中心。
- [ ] 切换三种 Mask，调整面积滑条，确认过滤变化。
- [ ] P 暂停/恢复；暂停时 S 保存并核对 JSON 中坐标与图片。
- [ ] Mask 预览时 S 仍保存彩色标注图；连续 S 不覆盖。
- [ ] Q / Esc / 关闭窗口后可重新打开相机。
- [ ] 再次运行全部离线测试。

代码保存在 [CargoVision-Mini 仓库](https://github.com/chen-yy2008/CargoVision-Mini) 的 `main` 分支，v0.2.0 使用附注 Tag 和 [GitHub Release](https://github.com/chen-yy2008/CargoVision-Mini/releases/tag/v0.2.0) 标记，保留历史 v0.1.0。用户明确同意本次以早期原型标准发布，独立点定量精度和真实内参校正继续列为未验收项，不以软件合成结果替代。

提交前使用 `git status --short` / `git diff --cached` 检查内容。`.venv/`、缓存、临时文件、实验输出、审查 ZIP、常见本地凭证与私钥路径由 `.gitignore` 排除；不要把令牌直接写入源码或文档。

## 9. 第一次 Windows 真实平面标定（无需棋盘格）

先在项目根目录执行 ` .\.venv\Scripts\python.exe -m pip check `，确认使用项目解释器。新电脑按第 1 节创建环境并安装 `requirements.txt`。

1. **固定相机与平面**：固定支架、关闭可能占用相机的软件，保持画面稳定。尽量锁定自动对焦/缩放，固定光照；不要手持相机标定。确认整张矩形四角都在画面内。
2. **量实际尺寸**：在桌面放平整 A4 纸或实测矩形。宽指 TL→TR，高指 TL→BL；A4 纵向摆放时示例为 210×297 mm，横向则交换，其他矩形使用尺量值。不要用像素宽高替代毫米边长。纸要平整，可用胶带在桌面保留原点、轴和区域边界，便于移走后测量。
3. **冻结并点选**：执行下面第一条命令。在窗口按 **F** 冻结同一帧，再按 **左上 TL → 右上 TR → 右下 BR → 左下 BL** 左键点选四角。编号会显示；U / Backspace / 右键撤销一个点，R 清空重选。相机画面未冻结时不接受点选。
4. **确认保存**：按 S 或 Enter。若文件已存在，按 Y 明确覆盖，N 取消覆盖；Esc / Q / 关闭窗口取消，不改旧文件。大图会按固定比例缩小，工具按实际 resize 比例换算点击；使用 AUTOSIZE 禁止手动缩放窗口，不用窗口外框猜坐标。
5. **检查并检测**：运行 `--inspect` 核对尺寸、分辨率、四角、轴和 pixel_frame，再运行 `main.py --calibration ...`。关闭标定工具会释放相机，无需同时打开两个摄像头程序。

```powershell
# 改为 --list-cameras 中确认的编号/后端，下面数值只是例子
$CameraIndex = 1
$CameraBackend = 'dshow'
.\.venv\Scripts\python.exe calibrate_plane.py --camera $CameraIndex --backend $CameraBackend --width-mm 210 --height-mm 297 --output calibrations/desk_plane.json
.\.venv\Scripts\python.exe calibrate_plane.py --inspect calibrations/desk_plane.json
.\.venv\Scripts\python.exe main.py --camera $CameraIndex --backend $CameraBackend --calibration calibrations/desk_plane.json
```

也可从真实照片点选，但后续检测必须保持相同相机设置、图像尺寸和空间，示例中的 `camera_photos/plane.png` 需要你自己准备：

```powershell
.\.venv\Scripts\python.exe calibrate_plane.py --image camera_photos/plane.png --width-mm 210 --height-mm 297 --output calibrations/desk_plane.json
```

画面显示原有 `CENTER (x,y)`（pixel）和新增 `MM (x,y)`。毫米原点是当初点选的 TL，X 沿 TL→TR，Y 沿 TL→BL，**不是屏幕默认缩放后的像素轴或机器人机械轴**。只在标定四边形内部输出毫米位置；边界点也允许，区域外显示 `OUTSIDE ROI`。按 S 成对保存标注 PNG 与 0.2 JSON。

移走纸后应维持同一个物理平面。首轮推荐贴近平面的彩色薄纸片、胶带或平面标记，避免高盒子顶面；有高度会产生视差，不能据此验证桌面平面的定位精度。不要移动相机、改变分辨率、明显改变对焦/变焦、桌面高度或更换设备；发生变化后重新标定/验证。程序能检查分辨率和配置关联，**不能自动知道相机被挪动了**。

## 10. 用独立验证点测毫米误差

选择至少 3 个、建议 5~10 个**没有用于计算 H 的位置**，分布在矩形中心和四周。用尺子沿原标定轴测量彩色薄标记中心的真实 X/Y；运行检测并按 S，从 JSON 中读取对应 `center_mm` 作为预测值，逐行填表。不要把四个拟合角点当作验证点，也不要用系统自己的预测值充当真值。

复制样例到本机输出目录，然后用 Excel / 文本编辑器替换所有合成数据和点名；保留英文列名，单位全部为 mm，CSV 使用 UTF-8，数字用小数点：

```powershell
# 仅首次复制；已有记录时换文件名，避免覆盖测量数据
if (Test-Path outputs/validation_real.csv) { throw '记录已存在，请换一个文件名' }
Copy-Item samples/validation_example.csv outputs/validation_real.csv
# 编辑并保存真实测量后，再执行：
.\.venv\Scripts\python.exe scripts/evaluate_calibration.py --input outputs/validation_real.csv --calibration calibrations/desk_plane.json --output outputs/validation_report.json
```

列为 `point_id,true_x_mm,true_y_mm,predicted_x_mm,predicted_y_mm`；也可提供含相同字段的 JSON 数组。指定 `--calibration` 可额外拒绝拟合角点和区域外真值。输出已存在时拒绝覆盖，请选择新文件名；不传 `--output` 则只打印。

统计定义：`dx=预测X−真实X`、`dy=预测Y−真实Y`，逐点距离误差 `sqrt(dx²+dy²)`；平均距离是距离误差的算术平均，最大值是最差点，`RMSE=sqrt(mean(dx²+dy²))`。均值 dx/dy 可看系统偏移，但正负抵消不能说明精度很好。脚本只能统计你提供的数据，不能证明点确实由尺子独立测得。

仓库样例仅为手算可核对的合成数据，预期平均距离 3.3333 mm、最大 5 mm、RMSE 4.08248 mm；**这些数值不是本项目真实相机精度**。软件合成透视测试的 0.0001 mm 容差也不代表实物误差；真实精度由你的设备和测量决定，不承诺低于 1 mm。

## 11. 可选进阶：棋盘格相机内参与去畸变

如果边缘畸变明显，另行拍摄棋盘格：格子在同一平面、打印不缩放并量单格边长，准备至少 5 幅、建议 15~25 幅同分辨率清晰照片。棋盘格需要覆盖画面不同位置和距离，具有不同倾斜角；不要只拍同一姿态或重复照片。完整内角点必须可见；在 `camera_photos/` 内新建 `chessboard/` 子目录，专门放这一批棋盘格照片。

以下 9×6 是**内角点列/行数**的例子（对应 10×7 方格），20 mm 是需实测的单格边长，不是默认设备参数：

```powershell
.\.venv\Scripts\python.exe calibrate_camera.py --images camera_photos/chessboard --cols 9 --rows 6 --square-mm 20 --output calibrations/camera.json
```

不要在同一个照片目录混放其他相机、其他分辨率或普通桌面图片。工具报告成功/失败文件、有效视图数、总体及逐图重投影 RMSE（pixel）；有效图不足会拒绝保存，重复观测会拒绝。重投影像素误差不是桌面毫米误差，仍需第 10 节的独立验证。已有内参文件默认拒绝覆盖，只有明确加 `--overwrite` 才允许替换。

开启内参后必须**重新做平面标定**，两条命令都加载同一内参：

```powershell
$CameraIndex = 1
$CameraBackend = 'dshow'
.\.venv\Scripts\python.exe calibrate_plane.py --camera $CameraIndex --backend $CameraBackend --intrinsics calibrations/camera.json --width-mm 210 --height-mm 297 --output calibrations/desk_undistorted.json
.\.venv\Scripts\python.exe main.py --camera $CameraIndex --backend $CameraBackend --intrinsics calibrations/camera.json --calibration calibrations/desk_undistorted.json
```

流程为 raw 帧 → `cv2.undistort`（保持原 K、原尺寸、不裁剪）→ 点选或颜色检测 → 同空间 H → 毫米坐标 → 标注与导出。raw 平面 H 不能用于 undistorted 图像。配置记录内参 id 和参数指纹，改写同 id 的参数也会拒绝混用；相机内参和工作平面标定都要求分辨率完全匹配。

## 12. V0.2 测试与学习入口

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py vision.py config.py io_utils.py calibration.py calibrate_plane.py calibrate_camera.py scripts tests
.\.venv\Scripts\python.exe -m pip check
```

v0.2.0 发布前全部 **129 项自动测试通过**。用户已完成真实平面标定及基本像素/毫米输出验收；**独立点定量毫米误差与真实内参/畸变校正仍未验收**。自动测试、用户反馈和历史开发检查分别记录于 TEST_REPORT.md；源码断点建议从 LEARNING_GUIDE.md 的 V0.2 部分开始。

## 13. Windows 摄像头偏好与分辨率

`--list-cameras` 仅列出当前能实际读取一帧的编号、后端、真实帧宽高和设备报告 FPS，不保存照片/偏好。默认检测 0..4，设备较多时用 `--scan-limit 10`（最大 20）。设备忙、权限不足或驱动问题会使其暂时未被列出；探测失败编号时可能出现 OpenCV 原生驱动日志，以最终可读列表为准。

成功启动摄像头、读到首帧且标定检查通过后，程序将索引、实际后端和实际分辨率写入项目根目录的 `local_settings/camera.json`。这个路径由程序文件位置决定，与 PowerShell/PyCharm 的工作目录无关，已加入 `.gitignore`。**首次无偏好时使用 0 并明确打印；它不代表已自动识别 USB。请先按列表逐个核对画面，再选择需要的 USB 摄像头。**

后续直接运行 `main.py` 恢复该偏好，无需交互输入。`--camera N` 总是优先并在成功后更新偏好；显式新选择不继承另一台相机的采集设置。保存的后端会固定使用，打开或读帧失败不悄悄换编号/后端；可用 `--backend auto` 明确要求重新尝试后端，或使用列表中的 `--backend dshow/msmf`。

此实现只保存 **OpenCV 索引＋后端**。OpenCV Python 没有可靠的通用 Windows 物理设备路径映射，因此不把 PnP 列表顺序猜成 OpenCV 编号，不显示未经证实的型号/USB 标识。插拔、重启、驱动或虚拟摄像头变化后，索引可能指向另一台设备；**程序不能保证检测这种重新编号**，每次启动均提示核对画面。需要永久物理设备绑定时应另行评估专用枚举实现，而不是宣称当前已做到。

可选配置采集尺寸，两个参数必须一起指定：

```powershell
# 640×480 是当前 OV4689 的用户验收基线，编号/后端仍需核对；检查实际返回尺寸
.\.venv\Scripts\python.exe main.py --camera 1 --backend dshow --width 640 --height 480
```

设置成功与否最终依据 `frame.shape`，不是只看 `cap.set()` 的返回值。设备拒绝请求会提示实际返回值；首帧实际尺寸被保存，下一次恢复同一尺寸。窗口上 `Capture WxH` 是实际输入尺寸；`Device FPS` 是驱动报告值，未知显示 unknown，顶部 FPS 是处理/显示循环测量值，二者不可混淆。不改焦距或变焦，默认不设置设备帧率，也不强行切换默认采集分辨率；仅在显式 --fps 或恢复对应本机请求时设置帧率。

加载平面或内参配置时，请求尺寸与标定不符会在设置设备前拒绝；实际返回尺寸与标定不符也会由 V0.2 原有检查拒绝，不能静默缩放 H。即使尺寸相同，换相机或姿态变化后仍需重新验证/标定。

四点工具也支持 `--backend`、`--width`、`--height`、`--fourcc`、`--fps`。如果识别使用了自定义采集尺寸，平面标定命令也必须指定相同设置，例如在第 9 节标定及识别命令上**同时**添加 `--width 640 --height 480`，并核对双方打印的实际宽高；新工具不改写旧标定矩阵或本机摄像头偏好。

本次不增加运行中热切换摄像头：Q 退出释放设备，再用 `--camera N` 重启选择即可。保存失败、设备故障和偏好写入失败都有中文提示；偏好无法写入时当前可读会话仍可继续，但不能宣称下次会记住。

## 14. 标定前检查 USB 摄像头采集模式

先退出 CargoVision、Windows 相机和其他占用设备的软件。用 `main.py --list-cameras` 列出可读编号，再逐个打开画面确认哪个是 USB；编号不是永久物理身份，不同后端的相同编号也不能直接认定为同一相机。

```powershell
# 改为你已核对画面的 USB 编号；这里的 1 只是命令示例
$CameraIndex = 1
.\.venv\Scripts\python.exe scripts/probe_camera.py --camera $CameraIndex --sizes 640x480
```

上面的命令限制为 640×480；若主动比较其他模式，可给 --sizes 添加尺寸，或省略 --sizes 使用完整候选列表。完整默认列表顺序尝试 DSHOW / MSMF × auto / MJPG / YUY2 × 640×480、1280×720、1920×1080、2560×1440、3840×2160，共 30 组。每组独立打开、预热 5 帧后测量 2 秒，总时限 15 秒。超时会结束该组子进程并回收设备，继续下一组；最慢可能约 8 分钟。Ctrl+C 可停止并保存已完成的报告。它只验证指定请求，**不枚举驱动完整能力列表**；更高尺寸可按设备说明用 `--sizes 4096x2160` 等单独尝试，不推断所有相机支持这些值。

省略 `--camera` 时只使用已保存的编号；没有偏好则要求明确指定，不替你猜另一台设备。工具不写摄像头偏好，不保存照片；数值 JSON 默认写入项目 `outputs/camera_probe_*.json`，已被 Git 忽略。可用 `--output` 指定新文件，但拒绝覆盖已有报告。

若另行排查高分辨率，可缩小范围、延长测量与总时限；1280×720 已有黑屏反馈，不应把以下实验当作正常使用的前置步骤：

```powershell
.\.venv\Scripts\python.exe scripts/probe_camera.py --camera $CameraIndex --backends dshow --formats auto mjpg yuy2 --sizes 640x480 1280x720 1920x1080 --seconds 5 --warmup 10 --timeout 25
# 另测 MSMF：先核对该后端下的设备编号，再用 --backends msmf
# 若需比较明确的 30 FPS 请求，在同一命令末尾加 --fps 30
```

每组报告严格分开以下证据：

| 字段 | 含义 |
| --- | --- |
| requested | 设备编号、请求后端/宽高/格式/FPS；auto 不主动设置 FOURCC，省略 fps 不设置帧率 |
| set_results | 各属性设置返回值，仅说明驱动是否确认；true 不等于实际生效，false 也不证明当前帧一定不是这个尺寸 |
| properties_after_set / actual.properties / last_properties | 设置后、首个测量帧后、最后一帧后的属性读回值；FPS、FOURCC 可能未知，或反映后端转换后的格式 |
| actual.width / actual.height、size_counts | 来自真实 `frame.shape` 的像素尺寸及各尺寸的帧数；不靠窗口大小或软件 resize 冒充高分辨率 |
| measured_read_fps / frames / sample_seconds | 预热后 `(帧数−1)/(末帧完成时刻−首帧完成时刻)`；少于两帧时 FPS 为 null |
| status / exact_resolution | read_ok 表示此次测量读帧成功且所有测量帧尺寸精确匹配；size_mismatch 表示读到其他尺寸，error/timeout/worker_error 须查看原因 |

`read_ok` 不代表所有属性生效，也不代表稳定性或标定验收。纯采集 read FPS 不含目标检测/预览，不等于窗口处理 FPS 或传感器曝光帧率；驱动缓冲/重复帧可能影响结果。返回 4K 帧不证明传感器原生 4K，也不证明清晰度提高。工具不调整曝光、对焦或图像转换逻辑。

确认模式后，使用已有宽高参数加可选格式/FPS 启动工作台：

```powershell
# 先测试不指定编码/FPS；不要把未经验证的 MJPG/30 FPS 当作默认保证
.\.venv\Scripts\python.exe main.py --camera $CameraIndex --backend dshow --width 640 --height 480 --fourcc auto
# 仅在检测报告和画面验证合适时，才使用类似的显式请求：
# .\.venv\Scripts\python.exe main.py --camera $CameraIndex --backend dshow --width 640 --height 480 --fourcc mjpg --fps 30
.\.venv\Scripts\python.exe main.py
```

启动终端并列打印请求、属性与真实帧值，预览仍沿用原有工作台。首帧及标定检查通过后，本机配置保存**实际宽高/后端**，以及可选 `requested_fourcc`、`requested_fps`；后二者只保留“请求”语义，下一次仍须检查是否生效。旧配置无需迁移。`--fourcc auto` 清除保存的格式请求；要恢复完全不设置 FPS 的会话，可显式 `--camera N` 重选并省略 `--fps`（同时把要保留的后端/宽高写上）。设备索引选择、命令行优先级及保存失败处理保持原样。

**发布时以用户实机结果为准**：OV4689 已验收模式为 640×480、约 30 FPS；1280×720 有黑屏反馈，重新插拔后 640×480 正常。此前开发环境曾在未确认物理身份的编号 2 上测得 720p 数组和约 24.75～29.54 read FPS，这些历史记录保留在 TEST_REPORT.md，但不作为 OV4689 的 720p 稳定性或原生能力证明，也不再作为本版推荐基线。

选好模式后保持相机安装、镜头、照明和工作平面固定，再进行第 9～11 节标定。平面工具必须显式使用同样的设备、后端、宽高、可选 FOURCC/FPS，例如：

```powershell
.\.venv\Scripts\python.exe calibrate_plane.py --camera $CameraIndex --backend dshow --width 640 --height 480 --fourcc auto --width-mm 210 --height-mm 297 --output calibrations/desk_480p.json
.\.venv\Scripts\python.exe main.py --camera $CameraIndex --backend dshow --width 640 --height 480 --fourcc auto --calibration calibrations/desk_480p.json
```

210×297 mm 只是 A4 示例，须核对实物及四角方向。若用了内参，两条命令均加载同一份、同采集尺寸的 `--intrinsics`。工具不自动换算旧 H 或旧内参；尺寸冲突仍拒绝毫米输出。即使尺寸相同，更换后端/格式/FPS 引起视野、裁剪、清晰度变化也要重新验证独立点，必要时重做内参及平面标定。最后检查 P/S/Q、Mask、窗口缩放、原尺寸导出，再做长时间稳定性与毫米误差验收。

## 15. 简易可视化启动器（v0.3 第一阶段）

**入口**：双击项目根目录 `Start_CargoVision.cmd`。它只检查并使用当前项目 `.venv\Scripts\python.exe`，正常时用 pythonw 打开中文界面。缺少虚拟环境或 Tkinter/OpenCV/NumPy 时显示中文说明及可复制的错误；不运行安装、更新或环境修改。启动失败日志在 `.cache/launcher_bootstrap.log` 或 `.cache/launcher_startup_error.log`。Tkinter 通常由 Windows 官方 Python 安装程序附带；如缺少，请自行按安装程序选项准备，不要尝试 pip 安装 tkinter。

窗口提供“打开实时检测”“选择摄像头”“工作平面标定”“参数设置”“退出”：

1. **选择/确认摄像头**：自动读取 `local_settings/camera.json` 的上次成功编号/后端，并明确标为“上次成功实际尺寸，本次待读取”。没有成功偏好时不猜编号。可扫描 0～4 或手填编号，再点“预览并确认摄像头”；预览画布用英文提示，核对实际画面后按 **C** 保存，**Q/Esc/关闭**取消。扫描不会自动改变选择；编号不能永久绑定物理 USB，插拔、重启后仍要核对画面。
2. **参数设置**：采集宽/高单位 pixel，最小面积 px²，新标定实测宽/高 mm；后端、可选格式/FPS、平面标定文件和可选内参均可在界面选择。首次请求保持 **640×480**，不自动继承较高分辨率；明确选择其他尺寸时提示黑屏风险。已有启动器设置会恢复；CLI 后来成功选择了别的设备时，启动器采用该设备并回到 640×480 基线。改了相机或采集请求后需预览确认再检测。
3. **已有标定直接使用**：在参数设置中选择平面 JSON，必要时选择同一份配套内参。界面区分“未加载：仅像素”“文件合法、待现场确认”“已现场确认”“标定不可用”。每次打开启动器，使用毫米坐标或内参前须勾选现场条件确认。该勾选不会持久化，也不证明相机真的没移动；相机、镜头、采集条件或平面变化后须重新验证/标定。文件内容或采集参数变化时旧确认失效；损坏、丢失、尺寸或 raw/内参关联不匹配会明确拒绝，**不会静默清空标定降级运行**。
4. **首次做平面标定**：填写实物测得的宽高（默认 210×297 mm 仅是 A4 示例），点“工作平面标定”选择保存位置。在原 OpenCV 标定窗口按 F 冻结、TL→TR→BR→BL 点选四角、S 保存。新文件成功保存后自动在启动器选中，再确认现场条件并打开实时检测；取消不采用未保存的新标定。已有文件仍需原工具明确确认才能覆盖。参数中的“新标定实测宽高”不会改写已选旧标定，旧文件的毫米尺寸会另行显示。
5. **打开实时检测**：继续使用原 OpenCV 工作台及 P/S/Q/Esc、Mask、面积滑条和原尺寸 PNG/JSON 导出。检测启动后，界面只在原程序写出本次成功采集信息时显示本次实际尺寸；实际帧不符合标定仍由原程序拒绝。参数只是请求，不能从 set 成功或窗口缩放推断采集尺寸。
6. **退出与诊断**：同一启动器一次只运行一个设备任务，扫描/预览使用独立进程并有超时保护。一般在原窗口按 Q 正常释放设备，启动器自动恢复可操作状态。“停止当前程序”用于故障处理，强制结束可能丢失未保存数据；关闭启动器时会询问是否停止仍运行的子程序。错误统一有中文摘要，下方保留驱动原文，点击“复制诊断信息”提供排查；完整日志在 `.cache/launcher/`。

设置存于 `local_settings/launcher.json`，摄像头实际成功偏好继续使用原 `camera.json`，两者均被 Git 忽略。保存采用临时文件原子替换；损坏配置会保留原文件并明确提示，通过界面重新保存或成功预览恢复，不必编辑 JSON。相对文件路径按项目目录解析，与双击时工作目录无关。

本阶段新增 `launcher.py`（界面与进程管理）、`launcher_config.py`（校验、状态和 argv）、`launcher_worker.py`（扫描/预览）及双击入口；原检测、标定数学、命令行和 JSON 数据格式保持不变。当前软件回归与真实设备检查边界见 TEST_REPORT.md。首次实机验收建议：确认 USB 预览 → 保存参数并重启恢复 → 选择已验收标定和现场确认 → 看像素/毫米及 OUTSIDE ROI → P/S/Q/Mask/保存 → 退出后重新打开设备。
