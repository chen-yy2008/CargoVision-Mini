# CargoVision Mini 源码学习指南（V0.1 → V0.2）

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

## 9. V0.2：先区分三种坐标和两个矩阵

V0.1 的 `center_px` 是图像上的像素质心。V0.2 不替换它，而是先检查标定，再可选添加 `center_mm`：

```text
raw BGR 帧
  ↓ 可选 calibration.undistort_frame(K, 畸变)，保持原 K / 原尺寸 / 不裁剪
raw 或 undistorted BGR 帧（之后每一步都保持这个空间）
  ↓ vision.detect_objects()
center_px：图像左上角为原点，单位 pixel
  ↓ calibration.add_workplane_coordinates()：分辨率、内参关联和 ROI 检查
calibration.pixel_to_workplane()：H 映射
  ↓
center_mm：标定 TL 为原点，X 沿 TL→TR、Y 沿 TL→BL，单位 mm
  ↓ main.analyze_frame()：同一帧绘图 + io_utils.build_result() / save_results()
```

这不是机器人机械坐标，没有 Z、机械零点或抓取规划。`center_mm` 只有 `mm_status == "valid"` 时存在；无标定时仍输出像素。检测框、十字、PNG 和 JSON 的 `center_px` 均对应当前 `pixel_frame`，不要把校正前后的像素混在一起。

同为 3×3 矩阵，`camera_matrix`（K）和 H 用途不同：K 描述针孔相机的焦距/主点（pixel），与畸变系数一起校正成像；H 把当前图像坐标映射到指定平面的毫米坐标。K 不能直接给出桌面毫米位置，H 也不能代替镜头畸变模型。

## 10. H 是怎么生成的

首先阅读 [calibration.py 的 create_plane_calibration()](calibration.py#L165)，在 `corners`、`matrix` 两处设断点。

```python
matrix = cv2.getPerspectiveTransform(
    corners.astype(np.float32),
    _rectangle_mm(width_mm, height_mm),
)
```

左边的四个输入点严格为 **TL→TR→BR→BL**，单位 pixel；右边依次是 `(0,0)`、`(width_mm,0)`、`(width_mm,height_mm)`、`(0,height_mm)`，单位 mm。这个对应关系决定了方向，不能只把点按某个 x 值排序就认为完成了标定，也不能误把照片分辨率填成真实边长。

`validate_corners()` 检查是否在图像内、相邻点是否重复/过近、四边形是否凸且顺序正确，以及面积是否足够。归一化叉积用于检查近共线；小面积区域不适合稳定拟合。`validate_plane_calibration()` 进一步检查 H 的数值/近奇异性、齐次分母是否跨零、四角映射是否与尺寸一致。

四个角点残差很小，只能说明 H 符合你输入的四对点，**不能说明真实定位误差很小**；错误尺量、点错实际边界或镜头畸变可能被四点拟合掩盖。

## 11. 从一个像素质心到毫米

阅读 [calibration.py 的 pixel_to_workplane()](calibration.py#L290)。设置断点观察 `point`、`denominator`、`mapped`。

把像素写为齐次向量 `[x,y,1]`，H 相乘得到 `[u,v,w]`，最后要做透视除法：

```text
u = H00*x + H01*y + H02
v = H10*x + H11*y + H12
w = H20*x + H21*y + H22
X_mm = u / w
Y_mm = v / w
```

代码用 OpenCV `perspectiveTransform()` 完成这一步，没有自行重写算法。透视场景的 `w` 会随位置改变，所以通常没有整幅画面通用的固定“每 pixel 等于多少 mm”。合成 demo 恰好使用 0.5 mm/pixel，是人为构造的简单测试，不能套到摄像头上。

转换前 `pointPolygonTest()` 先判断质心是否位于四角 ROI 内；区域外返回 `(None, "outside_roi")`，不输出外推值。边界点允许参与变换。转换后也检查是否有限，避免 NaN/Inf 进入 JSON。毫米元信息中 `valid` 表示配置/区域有效，**不表示已通过真实毫米精度验收**。

在 `main.analyze_frame()` 中对比 `objects` 和 `converted`：前者保持 V0.1 像素字段；后者是新字典，添加状态及合法的毫米值，不修改原检测列表。

## 12. 为什么先去畸变，再点选四角和识别

阅读 [calibration.py 的 undistort_frame()](calibration.py#L276) 与 `check_frame_context()`。raw 像素上的一个点，校正后可能移动；如果继续使用 raw 的 H，会将一个空间的坐标错误地交给另一个空间的映射。

因此平面标定工具和运行程序都采用 `cv2.undistort(frame, K, distortion, None, K)`，保持原 K、尺寸且不裁剪。平面配置记录 `pixel_frame` 和 `intrinsics_reference`，后者含内参 id 与参数指纹；哪怕 id 没变，只要参数被改写，就拒绝混用。分辨率不同也直接报错，不静默缩放 H。

不启用内参时，这条分支完全跳过，四点 raw 标定仍可独立使用。需要先实测判断畸变影响，不能认为打开去畸变就自然达到亚毫米精度。

独立进阶工具的 [calibrate_camera.py 的 calibrate_from_points()](calibrate_camera.py#L35) 中，`object_points` 是棋盘格内角点的 Z=0 毫米坐标，`observations` 是每张照片的亚像素角点。`calibrateCamera()` 估计 K/畸变后，`projectPoints()` 把已知棋盘格再次投回图像，与观测比较。

重投影 RMSE 是 `sqrt(mean(dx_px² + dy_px²))`，单位 pixel；它是模型对角点的拟合误差，不是工作平面的 mm 误差。至少 5 幅不同观测只是程序门槛，真实照片建议 15~25 幅，多位置、多倾角；模型是普通针孔/径向切向畸变，并非专用鱼眼模型。

`calibrate_images()` 的 `cornerSubPix(...,(5,5),...)` 表示半径 5，即 11×11 pixel 搜索邻域。邻域过大可能包含相邻棋盘角点、把精修位置拉偏；项目使用官方示例的较小窗口，并以小间距的合成棋盘格做回归验证。不要把“大窗口”简单理解为“更精确”，也不要靠精修挽救过小或模糊的照片。

## 13. 独立误差评估与误差来源

阅读 [scripts/evaluate_calibration.py 的 evaluate_measurements()](scripts/evaluate_calibration.py#L17)，断点看 `true_points`、`differences`、`distances`。真实值必须来自尺量等独立方法，预测值来自当前标定下的 `center_mm`。

```python
differences = predicted_points - true_points  # mm
distance = np.sqrt(dx_mm ** 2 + dy_mm ** 2)
rmse = np.sqrt(np.mean(dx_mm ** 2 + dy_mm ** 2))
```

示意中的变量名用于说明公式；项目实际用 `array[:, 2:] - true_points` 和 `np.linalg.norm()`。提供三个以上不同位置；指定平面配置时会拒绝拟合四角和区域外真值。正负误差平均可能互相抵消，所以同时看平均距离、最大值和 RMSE。

误差可能来自手动点选、纸张不平/尺寸误差、相机畸变、模糊、光照导致分割边缘变化、V0.1 整数质心取整，以及相机移动或目标高度产生的视差。透视图中像素区域质心映射到平面后，也不一定等于该物体在平面上的真实面积质心。首轮应使用贴近平面的薄标记，并用同一空间的真值来验证；不要把厚货物顶部当桌面测试。

## 14. 推荐学习顺序与五个实验

| 顺序 | 文件与真实函数 | 重点输入 → 输出 / 断点变量 |
| --- | --- | --- |
| 1 | `calibration.py:165 create_plane_calibration()` | 四角 px、实测宽高 mm → H 配置；看 corners / matrix |
| 2 | `calibration.py:290 pixel_to_workplane()` | center_px、合法平面配置 → 毫米字典/None 和状态；看 denominator / mapped |
| 3 | `calibration.py:276 undistort_frame()` | raw 帧、可选内参 → 同尺寸校正帧；看 K 与校正前后像素 |
| 4 | `calibrate_camera.py:35 calibrate_from_points()` | 多视角角点 → K、畸变、pixel 重投影误差；看 projected / squared_errors |
| 5 | `scripts/evaluate_calibration.py:17 evaluate_measurements()` | 独立真值与预测值 → 逐点及总体 mm 误差；看 differences / distances |

先用 `make_demo_calibration()` 取得合成字典副本做实验，不修改真实设备配置；每次实验后恢复默认值并跑测试。

1. **改变物理尺寸**：保持四角不变，将宽 290 mm 改为 580 mm 再重新创建 H。相同像素点的 X_mm 翻倍，Y_mm 不变；像素结果不会改变。
2. **改变点序**：交换第二、第三点，预期因交叉/顺序错误被拒绝；不要绕过校验硬保存。
3. **移动到 ROI 外**：将点从 `(110,130)` 改到 `(0,0)`。预期从 `(45,40)` mm 变成 outside_roi，且没有 center_mm。
4. **打破空间关联**：用合成 K 创建 undistorted 平面，再以 raw 模式调用 `check_frame_context()`；预期拒绝。更改分辨率或同 id 的畸变系数也应拒绝，而不是勉强给出坐标。
5. **修改独立误差样例**：样例三个距离为 5、0、5 mm，RMSE 为 sqrt(50/3)。把全部预测值改为等于真实值，统计应归零；这只验证脚本公式，不证明你的摄像头精度。
