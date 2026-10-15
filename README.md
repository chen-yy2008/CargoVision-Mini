# CargoVision Mini V0.1

一个适合学习的 Python + OpenCV 桌面视觉原型：从摄像头或本地图片识别多个红、绿、蓝目标，显示像素质心、边界框和目标数，保存同一帧的标注 PNG 与 JSON。V0.1 已通过 ChatGPT 离线代码审查及用户在 Windows 上的全部实机测试，版本标记为 `v0.1.0`。

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

JSON 固定字段为 `schema_version: "0.1"`、`coordinate_system: "image_pixel"`、`image_size`、`source`、带时区 `timestamp`、`objects`。每个目标包含 `id`、`color`、`center_px`、`bbox_xywh`、`contour_area_px2`。空白图像的 `objects` 是 `[]`。

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
├── AGENTS.md                       长期工程约定
├── main.py                         CLI、摄像头循环、按键和简单窗口
├── config.py                       HSV、默认面积和路径
├── vision.py                       Mask、轮廓、质心和标注
├── io_utils.py                     中文路径图片读取、JSON 组装、成对导出
├── scripts/
│   ├── __init__.py
│   └── make_demo.py                固定合成样图
├── samples/demo.png
├── tests/
│   ├── __init__.py
│   ├── test_vision.py              检测、几何和实际文件读写测试
│   └── test_main.py                CLI 和模拟摄像头控制流程测试
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

HSV 阈值需要现场调整，强反光、阴影和低饱和度会影响结果。轮廓质心并非真实重心或可用抓取点；外轮廓方法不精确扣除内部孔洞。FPS 是包含读取、检测和显示等待的循环速率，不是设备额定帧率。强行结束进程或断电时不保证两文件成对写完。

**使用边界：本版没有标定、毫米坐标、机器人通信或电机控制，不可将像素坐标直接作为机器人运动指令。** `outputs/` 可能包含个人画面和本机源路径，默认不提交。

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

代码保存在 [CargoVision-Mini 仓库](https://github.com/chen-yy2008/CargoVision-Mini) 的 `main` 分支，`v0.1.0` Tag 标记首个通过审查和用户实机验收的版本。本次整理只修正文档与关闭窗口的异常处理；后续版本继续在同一仓库增量迭代。GitHub Release 页面可按用户后续需要另行创建。

提交前使用 `git status --short` / `git diff --cached` 检查内容。`.venv/`、缓存、临时文件、实验输出、审查 ZIP、常见本地凭证与私钥路径由 `.gitignore` 排除；不要把令牌直接写入源码或文档。
