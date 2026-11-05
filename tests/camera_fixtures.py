"""摄像头测试夹具：属性全部显式配置，输出明确标记为 MOCK。"""

import os
from unittest.mock import MagicMock

import cv2
import numpy as np


def utf8_environment():
    """返回子进程专用的 UTF-8 环境副本，不修改用户或系统环境。"""
    return dict(os.environ, PYTHONIOENCODING="utf-8:strict", PYTHONUTF8="1", PYTHONUNBUFFERED="1")


def make_camera(frame=None, *, fps=None, fourcc=None, opened=True):
    """创建模拟采集器；尺寸来自合成帧，未给定的 FPS/FOURCC 用 0 表示未知。

    set() 只确认请求，不擅自改变实际帧或属性，允许测试驱动拒绝/协商不一致。
    所有返回值均显式设置，避免 float(MagicMock()) 意外得到 1.0。
    """
    frame = np.zeros((480, 640, 3), np.uint8) if frame is None else frame
    height, width = frame.shape[:2]
    properties = {cv2.CAP_PROP_FRAME_WIDTH: width, cv2.CAP_PROP_FRAME_HEIGHT: height,
                  cv2.CAP_PROP_FPS: 0 if fps is None else fps,
                  cv2.CAP_PROP_FOURCC: 0 if fourcc is None else cv2.VideoWriter_fourcc(*fourcc)}
    cap = MagicMock(name="MOCK camera", spec=["open", "isOpened", "read", "release", "get", "set", "getBackendName"])
    cap.open.return_value = opened
    cap.isOpened.return_value = opened
    cap.read.return_value = (True, frame)
    cap.release.return_value = None
    cap.get.side_effect = lambda prop: properties.get(prop, 0)
    cap.set.return_value = True
    cap.getBackendName.return_value = "MOCK"
    return cap
