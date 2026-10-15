# CargoVision Mini 源码学习指南

先运行样图，再按本文在真实源码中逐个寻找函数。所有实验只操作图片，不需要机械或电控硬件。

## 1. 先理解数据流

```text
main.py: run_camera() / run_image()
    ↓ 摄像头 cap.read() / io_utils.read_image()
uint8 NumPy ndarray，BGR，形状 (H, W, 3)
    ↓ vision.create_masks(): cvtColor → inRange → 开/闭运算
三张单通道 Mask，形状 (H, W)，值为 0 或 255
    ↓ vision.detect_objects(): findContours → contourArea → 面积筛选
vision.contour_center(): moments → (x, y)
    ↓ 普通 dict 组成的 objects 列表
vision.annotate_frame() → 彩色标注图
io_utils.build_result() → JSON 数据字典
io_utils.save_results() → outputs/ 下同名 PNG + JSON
```

输入和界面留在 `main.py`；检测只依赖数组；输出函数负责写文件。因此未来更换输入方式时，可以继续复用 `detect_objects()`，当前无需为未来硬件创建抽象类。

## 2. 数组索引与像素坐标

`frame.shape == (480, 640, 3)` 表示高 480、宽 640、三个通道。数组先行后列，坐标先 x 后 y：

```python
height, width = frame.shape[:2]
b, g, r = frame[y, x]  # 注意不是 frame[x, y]
```

左上角为 `(0, 0)`，向右 x 增大，向下 y 增大。最后一个像素坐标为 `(width - 1, height - 1)`。`bbox_xywh` 的 `(x, y)` 是左上角，`w/h` 是覆盖像素的宽高，所以绘框右下角用 `(x+w-1, y+h-1)`。

## 3. 为什么转到 HSV，红色为什么分两段

本项目 OpenCV 输入的通道顺序是 BGR。BGR 三个通道都容易随亮度变化；HSV 将色相 H 与饱和度 S、亮度 V 分开，更容易用色相范围筛选颜色，但仍会受光照与相机自动白平衡影响。

`vision.create_masks()` 里先执行 `cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)`。uint8 图像的 OpenCV H 范围是 **0~179**，不是 0~360；S、V 为 0~255。所有范围都在 `config.HSV_RANGES`。

红色色相绕过圆环端点，配置为 `0~10` 和 `170~179` 两段。`create_masks()` 用 `cv2.bitwise_or()` 合并两张红色 Mask；否则会漏掉偏向另一端的红色。合成图第二个红色矩形专门使用 H=175，测试还覆盖 H=179。

## 4. 从 Mask 到轮廓

`cv2.inRange()` 对每个像素同时检查 H/S/V 是否落在上下限内：满足时输出 255，否则为 0。Mask 不是概率图，也没有 confidence。

```python
part = cv2.inRange(hsv, lower, upper)
mask = cv2.bitwise_or(mask, part)
```

`create_masks()` 中的 3×3 开运算（先腐蚀后膨胀）去除小点，闭运算（先膨胀后腐蚀）填补小缝隙。它们也可能改变边缘位置，不能保证原图几何完全不变。

`detect_objects()` 用 `cv2.findContours(..., cv2.RETR_EXTERNAL, ...)` 提取外轮廓，不仅取最大轮廓，所以支持多个同色物体。每个轮廓再用 `cv2.contourArea()` 算面积，低于最小值就跳过。面积使用轮廓几何面积，不等于 Mask 白像素数量：包含端点的 101×101 矩形轮廓面积为 10000，而非 10201。

查看 Mask 时仍可能看到被面积过滤的小白点，因为面积筛选作用于输出目标，而不是回头修改 Mask。

## 5. 质心与检测框中心

在 `contour_center()` 中，轮廓矩提供 `m00`、`m10`、`m01`：

```python
cx = int(round(moments["m10"] / moments["m00"]))
cy = int(round(moments["m01"] / moments["m00"]))
```

`m00` 表示轮廓面积；后两个是 x/y 方向的一阶矩。相除得到轮廓几何质心并取整。`m00 == 0` 时不能除法，所以回退到边界框覆盖像素的中心。

规则矩形的质心和检测框中心重合。不对称三角形、L 形的质心往往偏向面积更大的一侧，不能直接用检测框中心替代。该质心也不是物体真实质量中心；孔洞、遮挡和外轮廓处理可能造成偏差。

## 6. 如何现场调参

先固定相机和漫射光照，再使用红/绿/蓝样品。若漏检，先切到对应 Mask，而不是直接把面积降到极小。

- Mask 完全黑：检查 `HSV_RANGES` 的 H 范围以及 S/V 下限，或目标是否在阴影中。
- Mask 大量选中背景：适当提高 S/V 下限或收窄 H 范围，注意可能同时漏掉暗物体。
- Mask 包含目标而没有框：降低 `Min area` 或命令行 `--min-area`。
- 小碎点很多：提高最小面积；必要时研究 `MORPH_KERNEL_SIZE`，但较大的核会吞掉小目标。

HSV 配置修改后重新启动程序，V0.1 不做在线 HSV 配置界面。面积和视图滑条在图片及相机窗口中均可使用。调参不等于标定，结果仍是像素。

## 7. 推荐学习的五个函数与实验

| 顺序 | 真实函数 | 输入 → 输出 | 动手实验与预期 |
| --- | --- | --- | --- |
| 1 | `vision.create_masks()` | BGR 数组 → 三色 Mask 字典 | 临时去掉红色第二段区间，样图右侧红框消失，相关测试失败；实验后恢复 |
| 2 | `vision.detect_objects()` | BGR 数组、最小面积 → objects、masks | 面积从 300 改为 11000，样图从 4 目标变为只剩绿色矩形 |
| 3 | `vision.contour_center()` | 单个轮廓 → 整数 `(x,y)` | 在独立实验图中画不对称三角形，比较质心与检测框中心的差异 |
| 4 | `vision.annotate_frame()` | 原图、objects、可选 FPS/暂停状态 → 标注副本 | 修改十字大小 16，定位数据保持不变；理解显示与识别的边界 |
| 5 | `io_utils.save_results()` | 标注图、结果字典、输出目录 → PNG/JSON 路径 | 连续按 S 保存，文件主干不同，图像和 JSON 成对出现 |

最值得先读的是前三个。然后查看 `main.run_camera()` 如何读取帧、处理 P/S/Q，以及为什么 `cap.release()` 必须放在 `finally` 中。

可以用下面的小实验直接复用算法：

```python
from scripts.make_demo import make_demo
from vision import detect_objects

objects, masks = detect_objects(make_demo(), min_area=11000)
print(objects)  # 只有绿色目标；没有窗口和摄像头依赖
```

## 8. 用测试理解工程边界

`tests/test_vision.py` 使用确定图像验证颜色、数量、中心误差（x/y 各不超过 1 像素）、噪点、空白及实际 PNG/JSON 读写。测试使用 `outputs/` 下临时目录，结束自动清理。

`tests/test_main.py` 用模拟摄像头验证后端回退、读取失败释放资源、暂停时不读新帧、保存、恢复与退出。模拟通过只证明控制流程，真实 USB 摄像头、驱动、光照和按键仍需本机验收。

修改一个参数后运行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`，观察变更对预期行为的影响。实验结束恢复默认参数并重新确认测试。
