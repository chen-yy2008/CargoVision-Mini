# 本机标定配置

实际平面和内参 JSON 默认保存在此处，被 Git 忽略；仅本说明和 `.gitkeep` 提交。

- `desk_plane.json`：raw 像素到工作平面 mm；由你测量和点选生成。
- `camera.json`：可选棋盘格内参和畸变。
- `desk_undistorted.json`：使用同一 camera.json 去畸变后重新点选的平面配置。

不要把合成 `samples/workplane_demo.json` 当作设备配置。移动相机或平面、更换设备、变更分辨率/变焦/对焦后重新标定或验证。详见根目录 README 第 9~11 节。
