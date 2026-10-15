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
