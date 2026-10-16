# CargoVision Mini V0.2（开发版）

一个适合学习的 Python + OpenCV 桌面视觉原型：保留红绿蓝多目标像素识别，V0.2 增加四点工作平面毫米定位、独立棋盘格内参工具和独立验证点误差统计。V0.1 已通过用户实机验收并发布 `v0.1.0`；V0.2 的真实相机标定、毫米精度及新功能审查仍待用户完成，暂不创建 `v0.2.0` Tag 或 Release。

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

```powershell
# 默认摄像头；也可尝试 --camera 1、--camera 2
.\.venv\Scripts\python.exe main.py --camera 0

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

1. 用 PyCharm 打开当前项目文件夹。
2. 在项目 Python Interpreter 中添加本地已有解释器，选择项目根目录下的 `.venv\Scripts\python.exe`。
3. 创建 `main.py` 的运行配置，Working directory 设置为当前项目根目录。
4. Parameters 填 `--image samples/demo.png` 或 `--camera 0`，然后运行。
5. 操作按键前点击 OpenCV 图像窗口，使其获得焦点；不要在 PyCharm 编辑器中按 S/Q。

不需要安装其他 GUI 框架，也不要在同一个环境混装多个 `cv2` 包。

## 4. 窗口操作

| 操作 | 效果 |
| --- | --- |
| Q / Esc / 关闭图像窗口 | 退出，释放摄像头和窗口 |
| P | 摄像头模式暂停/恢复；暂停时仍可调参和保存 |
| S | 保存当前帧的彩色标注图及对应 JSON；可连续保存而不覆盖 |
| Min area 滑条 | 实时调整最小轮廓面积，单位 px²；0 按 1 处理 |
| View 滑条 = 0 | 显示彩色原图及标注 |
| View = 1 / 2 / 3 | 显示红 / 绿 / 蓝 Mask，白色为被阈值选中的区域 |

面积滑条范围为 0~100000，鼠标不易精调时可通过 `--min-area` 指定初值。Mask 展示的是颜色分割及形态学处理后的结果，**尚未按最小面积删除白点**；小白点仍可能显示，但不会进入目标列表。即使预览 Mask，S 也保存对应帧的彩色标注图。图片模式不显示 FPS，也无需暂停。

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
├── tests/
│   ├── __init__.py
│   ├── test_vision.py              检测、几何和实际文件读写测试
│   ├── test_main.py                CLI 和模拟摄像头控制流程测试
│   ├── test_calibration.py         H、区域、配置和坐标空间验证
│   ├── test_calibration_tools.py   工具交互、内参和误差统计测试
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

用户已于 2026-10-15 确认 Windows 全部实机测试通过。以下清单保留，便于更换电脑、相机或后续迭代时重新验收：

- [ ] 打开实际摄像头，观察 FPS 和空白背景的 0 目标。
- [ ] 放入红、绿、蓝物体及两个分离的同色物体，核对框与中心。
- [ ] 切换三种 Mask，调整面积滑条，确认过滤变化。
- [ ] P 暂停/恢复；暂停时 S 保存并核对 JSON 中坐标与图片。
- [ ] Mask 预览时 S 仍保存彩色标注图；连续 S 不覆盖。
- [ ] Q / Esc / 关闭窗口后可重新打开相机。
- [ ] 再次运行全部离线测试。

代码保存在 [CargoVision-Mini 仓库](https://github.com/chen-yy2008/CargoVision-Mini) 的 `main` 分支，保留 `v0.1.0` Tag。V0.2 开发代码在可执行测试通过后按授权提交/推送；**等用户完成真实相机标定、毫米精度测试和代码审查后，再决定创建 `v0.2.0` Tag / Release**。

提交前使用 `git status --short` / `git diff --cached` 检查内容。`.venv/`、缓存、临时文件、实验输出、审查 ZIP、常见本地凭证与私钥路径由 `.gitignore` 排除；不要把令牌直接写入源码或文档。

## 9. 第一次 Windows 真实平面标定（无需棋盘格）

先在项目根目录执行 ` .\.venv\Scripts\python.exe -m pip check `，确认使用项目解释器。新电脑按第 1 节创建环境并安装 `requirements.txt`。

1. **固定相机与平面**：固定支架、关闭可能占用相机的软件，保持画面稳定。尽量锁定自动对焦/缩放，固定光照；不要手持相机标定。确认整张矩形四角都在画面内。
2. **量实际尺寸**：在桌面放平整 A4 纸或实测矩形。宽指 TL→TR，高指 TL→BL；A4 纵向摆放时示例为 210×297 mm，横向则交换，其他矩形使用尺量值。不要用像素宽高替代毫米边长。纸要平整，可用胶带在桌面保留原点、轴和区域边界，便于移走后测量。
3. **冻结并点选**：执行下面第一条命令。在窗口按 **F** 冻结同一帧，再按 **左上 TL → 右上 TR → 右下 BR → 左下 BL** 左键点选四角。编号会显示；U / Backspace / 右键撤销一个点，R 清空重选。相机画面未冻结时不接受点选。
4. **确认保存**：按 S 或 Enter。若文件已存在，按 Y 明确覆盖，N 取消覆盖；Esc / Q / 关闭窗口取消，不改旧文件。大图会按固定比例缩小，工具按实际 resize 比例换算点击；使用 AUTOSIZE 禁止手动缩放窗口，不用窗口外框猜坐标。
5. **检查并检测**：运行 `--inspect` 核对尺寸、分辨率、四角、轴和 pixel_frame，再运行 `main.py --calibration ...`。关闭标定工具会释放相机，无需同时打开两个摄像头程序。

```powershell
.\.venv\Scripts\python.exe calibrate_plane.py --camera 0 --width-mm 210 --height-mm 297 --output calibrations/desk_plane.json
.\.venv\Scripts\python.exe calibrate_plane.py --inspect calibrations/desk_plane.json
.\.venv\Scripts\python.exe main.py --camera 0 --calibration calibrations/desk_plane.json
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
.\.venv\Scripts\python.exe calibrate_plane.py --camera 0 --intrinsics calibrations/camera.json --width-mm 210 --height-mm 297 --output calibrations/desk_undistorted.json
.\.venv\Scripts\python.exe main.py --camera 0 --intrinsics calibrations/camera.json --calibration calibrations/desk_undistorted.json
```

流程为 raw 帧 → `cv2.undistort`（保持原 K、原尺寸、不裁剪）→ 点选或颜色检测 → 同空间 H → 毫米坐标 → 标注与导出。raw 平面 H 不能用于 undistorted 图像。配置记录内参 id 和参数指纹，改写同 id 的参数也会拒绝混用；相机内参和工作平面标定都要求分辨率完全匹配。

## 12. V0.2 测试与学习入口

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py vision.py config.py io_utils.py calibration.py calibrate_plane.py calibrate_camera.py scripts tests
.\.venv\Scripts\python.exe -m pip check
```

本次自动测试、合成图片和原生窗口程序化检查见 TEST_REPORT.md；**V0.2 真实内参、真实平面和毫米误差尚未实测**。源码断点建议从 LEARNING_GUIDE.md 的 V0.2 部分开始。
