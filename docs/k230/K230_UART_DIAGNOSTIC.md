# K230 v1 UART 诊断通信说明

更新时间：2026-11-19

## 1. 用途与范围

第一版用于验证 K230 与 STM32 之间的诊断数据链路，并将视觉请求接入现有识别流程。它不是最终运动控制协议。

- K230 收到 `CAPTURE` 后等待下一帧有效图像并执行/复用该帧识别结果。
- 有目标时返回 `RESULT`；无目标时返回 `NO_TARGET`；处理异常时返回 `ERROR`。
- 当前没有 `MOVE` 指令发送路径，不触发电机动作。
- UART 配置默认关闭。
- 当前结果中的 `PX` 表示图像像素坐标，不是毫米坐标。

## 2. 串口参数与引脚

| 项目 | K230 侧约定 |
| --- | --- |
| UART | UART2 |
| 波特率 | 115200 |
| 数据格式 | 8 data bits, no parity, 1 stop bit（8N1） |
| 流控 | 无 |
| 消息编码 | ASCII |
| 消息结束 | LF（\n） |
| TX | GPIO11 / TX2 |
| RX | GPIO12 / RX2 |
| 逻辑电平 | 3.3 V TTL |

建议从 K230 正面 40Pin 排针接线：物理 pin 5 为 GPIO11/TX2，物理 pin 3 为 GPIO12/RX2。板背面 4P UART2 接口也有对应的 GND、3V3、RX2、TX2 丝印，使用前先按板卡丝印和官方引脚图核对方向。

与 STM32 连接时：
- K230 GPIO11（TX2）接 STM32 UART RX。
- K230 GPIO12（RX2）接 STM32 UART TX。
- 两端 GND 共地。
- 两块板各自供电；不要把 K230 的 3V3 引脚当作 STM32 或其他设备的电源输出。
- 接线前确认 STM32 端 UART 逻辑电平与 3.3 V TTL 兼容；若不兼容，先设计合适的电平转换。

官方硬件资料：
- [01Studio K230 UART 接线说明](https://wiki.01studio.cc/docs/canmv_k230/basic_examples/uart/)
- [Kendryte CanMV K230 UART API](https://www.kendryte.com/k230_canmv/zh/v1.6/api/machine/K230_CanMV_UART模块API手册.html)

## 3. 第一版消息示例

STM32 请求：

```text
CAPTURE,J42,120.5,-5.0,DIAG\n
```

示例表示任务 ID 为 `J42`，STM32 上报的机械位置为 X=120.5 mm、Y=-5.0 mm，任务类型为 `DIAG`。当前机械位置仅作为请求上下文，K230 仍返回像素诊断结果。

K230 有目标时的示例响应：

```text
RESULT,J42,18,PX,1,1,red,120,87\n
```

其中 `J42` 用于关联请求，`18` 是示例帧序号，`PX` 明确坐标类型为像素。其余目标字段按当前本地协议实现解析；本示例不应被当作机械坐标报文。

无目标时返回 `NO_TARGET`，处理异常时返回 `ERROR`。具体错误内容以板端协议实现为准。双方按 LF 分帧，接收端必须按字节流处理半包和粘包，不能假设一次 read 就对应一条完整消息。

## 4. 本地实现与测试记录

K230 v1 本地工作区中的相关文件：

- `board/uart_link.py`：UART 初始化、FPIOA 引脚复用、行解析、超时、短写检查和异常恢复。
- `board/app.py`：接入 CAPTURE 请求和按请求应答。
- `board/settings.json`：UART 配置，默认关闭。
- `tests/test_uart_link.py`：协议层离线测试。
- `tests/test_uart_app.py`：视觉应用集成测试。
- `tools/uart2_loopback.py`：独立 UART2 物理回环测试脚本。

本地开发报告记录 16 项 UART 离线测试、211 项 Windows 对照回归通过。上述 K230 源码和测试脚本目前仍在独立本地工作区，尚未随本次文档提交到 GitHub。

## 5. UART2 物理回环测试

目的：不连接 STM32，仅验证 K230 UART2 的 TX/RX 物理收发。

1. 断开 K230 电源。
2. 用一根杜邦线短接 K230 GPIO11（TX2）与 GPIO12（RX2）。
3. 不连接 3V3，也不连接摄像头、STM32 或电机。
4. 上电后通过 USB REPL 运行本地 `tools/uart2_loopback.py`。
5. 默认发送 20 条带序号消息，每 500 ms 一条；每条等待回传最多 250 ms，并逐字节核对消息内容及末尾换行。
6. 预期通过条件：发送 20、接收 20、失败 0。
7. 测试结束后脚本调用 `deinit()`；断电后拆除跳线。

**截至 2026-11-19，物理回环尚未执行。** 测试脚本已准备，但尚未验证 GPIO11/12 的真实电气收发。

## 6. USB REPL 与 UART2 的区别

- USB REPL 使用电脑枚举出的 COM6，用于 CanMV IDE/终端交互。
- UART2 使用板上的 GPIO11/TX2 与 GPIO12/RX2，是另一组独立物理引脚。
- COM6 能进入 MicroPython `>>>` 只证明 USB REPL 正常，不代表 UART2 GPIO 回环已经通过。

## 7. 当前安全边界

- 不把 `PX` 像素值解释为毫米坐标。
- 不从当前请求中的机械 XY 推导未经标定的机械绝对坐标。
- 不发送 `MOVE` 或其他电机动作命令。
- 未确认 STM32 的回零、位置有效性、停稳状态和坐标参考点前，不启用正式运动控制。
