# 第三方依赖与方案来源

核对日期：2026-10-15。项目应用代码按任务书编写，没有整段引入其他仓库源码或外部图片；样图由 `scripts/make_demo.py` 自行生成。以下是通过包依赖调用的成熟方案及 API 参考记录。

## 依赖选择和许可证

| 依赖 / 上游 | 使用版本 / 许可 | 用途与选择理由 |
| --- | --- | --- |
| [OpenCV 官方仓库](https://github.com/opencv/opencv) | 4.12.0，Apache-2.0；[对应 LICENSE](https://github.com/opencv/opencv/blob/4.12.0/LICENSE) | HSV、二值 Mask、形态学、轮廓、矩、摄像头和轻量窗口；官方模块已经满足 V0.1，无需额外检测框架 |
| [opencv-python 打包仓库](https://github.com/opencv/opencv-python) | PyPI 4.12.0.88，打包代码 MIT；[仓库许可证](https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt) | 使用 Windows CPU 二进制 wheel，提供桌面窗口；不使用 contrib、headless 或自行编译 |
| [NumPy 官方仓库](https://github.com/numpy/numpy) | 2.2.6，BSD-3-Clause；[对应 LICENSE](https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt) | 图像数组、阈值数组和图像字节编码输入；与当前 OpenCV wheel 的 NumPy 2.x 约束配合 |

官方仓库提供持续维护的源码、问题跟踪和文档。当前选择固定版本以保持 V0.1 可复现，并非声称它们是最新版本。已在本机 Python 3.12.14 / Windows x64 安装并通过 `pip check` 与离线测试；未据此承诺所有 Python 或平台兼容。

这几个上游许可均允许在其条件下使用与分发；应用目前仅通过安装包调用公开 API，没有把依赖源码重新授权为本项目代码。项目自身尚未选定开源许可证，不代替用户决定授权方式。

## 实际安装包的许可证位置

已查看当前 wheel 中随附的完整许可文件：

- `.venv/Lib/site-packages/opencv_python-4.12.0.88.dist-info/LICENSE.txt`
- `.venv/Lib/site-packages/opencv_python-4.12.0.88.dist-info/LICENSE-3RD-PARTY.txt`
- `.venv/Lib/site-packages/numpy-2.2.6.dist-info/LICENSE.txt`

OpenCV/NumPy 的二进制包可能携带其他组件的条款，例如媒体组件或数值库。这里的上游主许可证表不替代 wheel 中完整第三方许可。当前交付通过 `requirements.txt` 安装依赖，不提交或重新打包 wheel。未来若分发可执行包或附带二进制，应保留实际分发版本的完整版权、许可证及适用 NOTICE，重新检查所包含组件，不能只附本表。

## 参考文档及使用边界

- [OpenCV：inRange / HSV](https://docs.opencv.org/4.x/da/d97/tutorial_threshold_inRange.html)：参考颜色阈值 API 的含义；项目独立组织三色区间与数据流。
- [OpenCV：形态学](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html)：参考开/闭运算语义。
- [OpenCV：轮廓特征](https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html)：参考面积、边界框、矩与质心计算。
- [opencv-python 安装说明](https://github.com/opencv/opencv-python#installation-and-usage)：同一环境只选择一个 `cv2` 提供包；本版需要窗口，所以选择 `opencv-python`。

没有复制上述页面的图像资源或大段示例代码。未来重要功能应先调查官方或维护良好的 GitHub 方案，记录版本、维护情况、许可证、依赖、验证结果和采用理由，再做增量实现；本记录不预先批准任何未来依赖。

## V0.2 方案调查与采用记录（2026-10-16）

保持 `opencv-python==4.12.0.88` 与 `numpy==2.2.6`，没有增加依赖或复制外部仓库源码。调查以 OpenCV 官方仓库的 4.12.0 示例和官方教程为主；4.x 文档站可能显示较新 4.x 文档，采用的接口已经在当前安装的 4.12.0 实际测试。

| 官方来源 | 采用方式与理由 |
| --- | --- |
| [OpenCV 官方单应性教程](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html) | 使用成熟的 getPerspectiveTransform / perspectiveTransform；人工输入恰好四对可信点，不另写求解器，不引入特征匹配框架或对四点套用无冗余意义的 RANSAC |
| [OpenCV 官方相机标定教程](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html) | 使用 findChessboardCorners → cornerSubPix → calibrateCamera → projectPoints；独立计算二维角点重投影 RMSE，区分 pixel 拟合误差与 mm 实测误差 |
| [OpenCV 4.12.0 calibrate.py](https://github.com/opencv/opencv/blob/4.12.0/samples/python/calibrate.py) | 参考官方棋盘格采集/多图求解的流程与内角点规格；项目独立实现简洁 CLI、JSON 校验、失败提示和测试，没有复制其源码 |
| [OpenCV 4.12.0 许可证](https://github.com/opencv/opencv/blob/4.12.0/LICENSE) | 官方实现为 Apache-2.0，使用已有 wheel 的公开 API；继续遵守 wheel 随附的完整第三方条款，不给本项目擅自选择开源许可证 |

本项目去畸变有意选择保持原 K、原尺寸、不裁剪的单一路径，以便平面标定与识别严格共享像素空间；不直接照搬示例里改变新 K 并裁剪 ROI 的流程。内参内容指纹用于防止配置混用，不是设备身份认证。无需 OpenPnP 依赖，也未复用其源码。合成棋盘格图案和投影角点由测试自行生成；它们不能替代真实照片或证明实际测量精度。
