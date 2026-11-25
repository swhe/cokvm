# CoKVM Linux 控制端设计（纯键鼠，无视频）

日期：2026-11-25
状态：已确认，待实现
范围：`control/linux/`，新增 Linux 控制端

## 1. 目标与非目标

### 目标

- 在 Linux 控制机上抓取本机键盘/鼠标，经 BLE VSS 协议转发给 CoKVM Dongle。
- 不做视频采集：受控机自带物理显示器，用户在旁边直接看屏幕。
- 用 `Ctrl+Alt+Esc` 在“控制受控机”和“使用本机”之间切换。
- BLE 断开（掉线、拔 dongle、受控机重启）时立即释放本机键鼠。
- 首次使用自动完成 BLE 配对（6 位 passkey），后续自动重连。
- 鼠标使用绝对坐标，按受控机分辨率换算到 `17280 × 17280` 逻辑网格。

### 非目标

- 视频采集与显示（V4L2、窗口、GUI）。
- macOS / Windows 客户端改动。
- 固件改动。
- OTA/DFU、多控制端并发（Dongle 本身只支持单连接）。
- 触摸板支持（见 6.5）。
- 键盘 LED 主动同步（见 6.4）。

## 2. 已确认的决策

| 主题 | 决策 |
| :--- | :--- |
| 形态 | 极简 CLI，单进程，无视频 |
| 实现语言 | Python 3，依赖 `bleak`、`python-evdev`、`dbus-fast` |
| 切换热键 | `Ctrl+Alt+Esc`，同一热键进出 |
| 释放状态 | 继续只读监听键盘以捕获热键，但不 grab |
| 掉线行为 | 立即释放 `EVIOCGRAB`，退避重连，重连后保持 MONITOR |
| 设备选择 | 自动枚举 + 能力过滤 + include/exclude |
| 配对 | 内置 BlueZ `Agent1`，终端输入 6 位码 |
| 鼠标映射 | 相对位移按受控机分辨率换算，可乘灵敏度 |
| 许可证 | GPLv2，与 `control/macos/`、`control/win/` 一致 |

## 3. 架构

单进程 `cokvm-linux run`。进程内三块并发：

- **asyncio 主循环**：BLE 连接/重连、Agent1 配对、VSS 发送队列、状态机。
- **输入读取**：每个设备的 fd 通过 `loop.add_reader()` 注册回调，evdev 事件直接在 asyncio 循环里处理，不额外开线程。
- **状态机**：`MONITOR`（未抓取，被动监听热键）与 `CAPTURING`（已 grab，转发键鼠）。状态切换只在主线程执行。

选择单进程的理由：掉线释放、热键切换、发送节流共享同一份状态，避免“键鼠被抓住但无人释放”的窗口。

## 4. 协议要点（来自 `docs/protocols.cn.md`）

- 服务 UUID `FF00`；DATA 特征 `FF1D`（Write Without Response，Write Authenticated）；INFO 特征 `FF2C`（Read，Read Authenticated）。
- 帧固定 22 字节，小端：`0x4B 0x4D version type data[8] reserved[10]`；`version = 0x00`，`reserved` 全 0。
- `type = 0x01` 键盘：`data[0]` 修饰键位（LCtrl `0x01`、LShift `0x02`、LAlt `0x04`、LGUI `0x08`），`data[1]` 固定 0，`data[2..7]` 最多 6 个 HID usage。
- `type = 0x02` 鼠标：`data[0]` 按键位，`data[1..2]` X（int16，0–17280），`data[3..4]` Y，`data[5]` 滚轮（int8，-127–127，一格 ±120），`data[6..7]` 保留 0。
- `type = 0x03` LED 状态：v1 不下发。
- 连接后读取 `FF2C`，返回 ASCII `"OK"` 表示链路已认证；失败时 `FF1D` 写入会被拒绝。
- 单帧要求 ATT MTU ≥ 25；固件 L2CAP TX MTU 为 65，满足。
- 每帧鼠标都会把指针移到给定绝对坐标；发滚轮帧必须复用最近一次的坐标与按键状态。
- 协议只支持修饰键 LCtrl/LShift/LAlt/LGUI，HID usage 仅 `0x00–0x65`。

## 5. 组件划分

目录：`control/linux/`

```
control/linux/
├── pyproject.toml
├── README.md
├── LICENSE                 # GPLv2
├── src/cokvm_linux/
│   ├── __init__.py
│   ├── cli.py
│   ├── app.py
│   ├── vss.py
│   ├── keymap.py
│   ├── devices.py
│   ├── input_source.py
│   ├── mouse.py
│   ├── hotkey.py
│   ├── sender.py
│   ├── ble.py
│   └── agent.py
└── tests/
    ├── test_vss.py
    ├── test_keymap.py
    ├── test_mouse.py
    ├── test_hotkey.py
    ├── test_devices.py
    └── test_app_integration.py
```

| 模块 | 职责 | 依赖 |
| :--- | :--- | :--- |
| `vss.py` | 22 字节帧编码（键盘/鼠标/LED），纯函数 | 无 |
| `keymap.py` | evdev `KEY_*` → HID usage / 修饰键位，只覆盖 `0x00–0x65` | evdev 常量 |
| `devices.py` | 设备枚举、能力过滤、include/exclude、列表输出 | python-evdev |
| `input_source.py` | 事件读取、grab/release 封装；可替换接口，便于测试 | python-evdev |
| `mouse.py` | 相对位移累积、夹边界、滚轮换算、复用最近坐标 | 无 |
| `hotkey.py` | `Ctrl+Alt+Esc` 和弦状态机 | 无 |
| `sender.py` | 发送队列与节流：键盘优先、运动合并、离散事件不丢 | 无 |
| `ble.py` | 扫描、连接、`pair()`、读 `FF2C`、断线回调、退避重连、无响应写入 | bleak |
| `agent.py` | BlueZ `Agent1`（`KeyboardOnly`），`RequestPasskey` 时在终端提示输入 6 位码 | dbus-fast |
| `app.py` | 状态机、队列消费、节流、信号处理、安全兜底 | 以上 |
| `cli.py` | 子命令与参数解析 | argparse |

`vss.py`、`keymap.py`、`mouse.py`、`hotkey.py` 为纯逻辑，单元测试不需要 BLE 或 root 权限。

## 6. 详细设计

### 6.1 设备枚举与过滤

- 用 `evdev.list_devices()` 枚举 `/dev/input/event*`，打开后按能力分类：
  - **键盘**：`EV_KEY` 且包含 `KEY_A`（字母区能力），排除 `BUS_VIRTUAL`。
  - **鼠标**：包含 `REL_X` 与 `REL_Y`，或包含 `ABS_X`/`ABS_Y` 且带 `BTN_LEFT`。
- 排除：只有电源键/lid/开关的设备（`KEY_POWER`、`EV_SW` 且无其他按键）、`BUS_VIRTUAL` 设备、触摸板（见 6.5）。
- `--include` / `--exclude` 接受设备名或 `/dev/input/by-id/*` 路径的 fnmatch 模式，`--exclude` 优先。
- `cokvm-linux list-devices` 打印设备名、路径、bus、键盘/鼠标能力，便于排查权限与过滤结果。
- 设备热插拔：v1 在 MONITOR 下每 2 秒重新枚举一次；CAPTURING 中新插入的设备不自动抓取，退出后重新枚举。CAPTURING 中被拔掉的设备自动从集合移除（见 7.2）。

### 6.2 键盘转发

- 维护修饰键位图与当前按下的非修饰键集合（最多 6 个）。
- 任何状态变化都发送一帧完整状态：修饰键位 + 6 个 usage 槽位（不足补 0）。
- 超过 6 个非修饰键时丢弃第 7 个及之后的按下，并在 stderr 告警；对应释放事件仍按当前集合重新计算。
- 左右修饰键映射到同一 bit（RCtrl→`0x01`，RShift→`0x02`，RAlt→`0x04`，Super→`0x08`）。
- usage 不在 `0x00–0x65` 的键忽略（媒体键、多媒体/厂商键）。
- `CapsLock` 作为普通键转发，由受控机自行翻转 LED；v1 不发送 LED 状态帧。
- 键盘事件不丢：独立于鼠标的发送优先级，队列满时优先保留键盘帧。

### 6.3 鼠标转发

- 相对位移按受控机分辨率换算：

  ```
  x_grid += dx_px * 17280 / target_width  * sensitivity
  y_grid += dy_px * 17280 / target_height * sensitivity
  clamp 到 [0, 17280]
  ```

  默认 `--target-resolution 1920x1080`，`--sensitivity 1.0`。
- 进入 CAPTURING 时坐标重置为中心 `(8640, 8640)`。
- 滚轮：`REL_WHEEL` 每格 ±1 → ±120，单帧夹到 ±127，超出的格数丢弃并在 stderr 告警；`REL_HWHEEL` 忽略。
- 滚轮帧复用最近一次的 X/Y 和按键位。
- 按键映射：`BTN_LEFT`→`0x01`、`BTN_RIGHT`→`0x02`、`BTN_MIDDLE`→`0x04`、`BTN_SIDE`→`0x08`、`BTN_EXTRA`→`0x10`，其余忽略。
- 鼠标运动只保留最新坐标；队列积压时丢旧运动帧，不丢按键与滚轮。
- 发送节流：运动帧每 8ms 合并一次（约 125Hz）；按键变化和滚轮立即发送。

### 6.4 LED 与键盘状态

- v1 不发送 `type = 0x03`。受控机收到 `CapsLock` 键后自行翻转 LED，与 Windows 控制端对 Num Lock 的处理一致。
- 协议允许控制端不下发 LED 状态帧；文档中注明该限制。

### 6.5 触摸板

- 触摸板通过 `ABS_MT_*` 多点协议上报，不是相对位移；直接读 evdev 无法得到指针移动。
- v1 枚举时跳过带 `ABS_MT_POSITION_X`/`ABS_MT_POSITION_Y` 的设备，`list-devices` 标注“touchpad (unsupported)”。
- 后续如需要，再基于 libinput 单独设计。

## 7. 状态机与热键

### 7.1 状态

- **MONITOR**：所有候选设备以只读方式打开（不 grab）。本机键鼠正常工作。每 2 秒重枚举设备。
- **CAPTURING**：所有候选设备 `EVIOCGRAB`。键盘/鼠标事件转发给 Dongle；热键被吞掉，不转发。

### 7.2 进入与退出

- MONITOR → CAPTURING：检测到 `Ctrl+Alt+Esc` → 对所有设备 `grab()` → 发送一帧“全键释放”（修饰键 0、6 个槽位全 0）清理受控机状态 → 鼠标坐标重置为中心。
- CAPTURING → MONITOR：再次检测到 `Ctrl+Alt+Esc` → 发送全键释放 → 等待发送队列最多 200ms → 对所有设备 `release()`。
- 设备在 CAPTURING 中消失（拔出）：2 秒巡检发现后立即释放并回 MONITOR（避免只拔键盘时无法按热键），随后在 MONITOR 下重新枚举。

### 7.3 和弦判定

- `Ctrl`（左或右）+ `Alt`（左或右）+ `Esc` 三键同时按下即触发，顺序不限。
- 触发后进入 150ms 冷却期，期间不重复触发；`Esc` 抬起后重置。
- 进入 CAPTURING 时那一组按键本来就没有转发（MONITOR 不转发任何键）。
- 退出 CAPTURING 时，Ctrl/Alt 可能已先作为普通修饰键转发（单独按下无副作用），Esc 及触发后的事件不转发；随后发送全键释放帧清理受控机状态。
- 被动监听无法吞键，因此 MONITOR 状态下按 `Ctrl+Alt+Esc` 也会传给本机应用；该组合在常见桌面上无绑定，文档中说明。

## 8. BLE 连接与配对

### 8.1 扫描与连接

1. 用 `BleakScanner` 按完整设备名 `CoKVM-Dongle` 与服务 UUID `FF00` 扫描，超时 10 秒。
2. `BleakClient(address)` 连接，超时 15 秒。
3. 连接后读取 `FF2C`：该读取会触发安全升级。返回 `"OK"` 进入下一步；失败则显式 `client.pair()` 后重试一次，仍失败则断开并按 8.4 重连。

### 8.2 Agent1 配对

- 启动时用 `dbus-fast` 在 `/org/bluez/cokvm_agent` 导出 `org.bluez.Agent1`，能力 `KeyboardOnly`，并调用 `org.bluez.AgentManager1.RegisterAgent` + `RequestDefaultAgent`。
- `RequestPasskey`：在 `/dev/tty` 提示“输入 Dongle 控制台显示的 6 位配对码”，读取后返回 `uint32`。非交互环境（无 tty）直接返回失败，提示改用 `bluetoothctl` 预配对。
- Agent 注册失败（D-Bus 无权限等）不是致命错误：记录警告，已绑定设备仍可连接，新设备需先用 `bluetoothctl` 配对。
- `RequestConfirmation` / `RequestAuthorization`：返回成功（Dongle 为 Display Only，正常流程不会走到确认分支；保留实现以防固件配置变化）。
- 配对成功后 BlueZ 自动保存 bond，后续无需重新输入。

### 8.3 发送

- `client.write_gatt_char(FF1D, frame, response=False)`。
- 每次写入用 `asyncio.wait_for` 限制 1 秒；超时或抛异常计入失败。
- 连续 3 次写失败视为断线，走 8.4。

### 8.4 断线与重连

- `BleakClient` 的 `disconnected_callback` 触发时：**立即释放 `EVIOCGRAB`**、清空发送队列、回到 MONITOR。
- 重连退避：1s、2s、4s、8s、16s、30s 封顶，无限重试，直到进程退出。
- 重连成功后保持 MONITOR，不自动抓取，避免用户正在本机操作时键鼠被再次吃掉。
- 重连期间保持 MONITOR：按热键不会进入 CAPTURING，直到链路重新认证成功；断线时 CAPTURING 已释放，不存在“无链路的抓取态”。

## 9. 安全兜底

所有退出路径都必须先释放 grab：

- `SIGINT` / `SIGTERM`：设置停止标志 → 释放 grab → 关闭 BLE。
- 未捕获异常：`try/finally` + `atexit` 双重释放。
- BLE 断线、连续写失败：立即释放。
- 进程被 `SIGKILL` 或崩溃：内核在 fd 关闭时自动解除 `EVIOCGRAB`，作为最后保险。

释放前最多等 200ms 让发送队列刷完，避免按键残留在受控机上。

## 10. CLI

```
cokvm-linux run [选项]
cokvm-linux list-devices
cokvm-linux scan            # 仅扫描 BLE 设备，便于排查
```

`run` 选项：

| 选项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--target-resolution WxH` | `1920x1080` | 受控机分辨率，用于鼠标换算 |
| `--sensitivity F` | `1.0` | 鼠标灵敏度系数 |
| `--include PATTERN` | 空 | 只抓匹配的设备（名称或 by-id 路径，可重复） |
| `--exclude PATTERN` | 空 | 排除匹配的设备（可重复，优先于 include） |
| `--device-name NAME` | `CoKVM-Dongle` | BLE 设备名 |
| `--dry-run` | 关 | 不发 BLE，把帧以十六进制打印到 stderr |
| `--verbose` | 关 | 调试日志 |
| `--no-grab` | 关 | 只监听不 grab，用于本地验证事件解析 |

`--dry-run` 与 `--no-grab` 用于无 Dongle 时开发和测试。

## 11. 错误处理与日志

- 日志写 stderr，格式 `时间 级别 消息`；`--verbose` 时输出 evdev 事件与帧十六进制。
- 可恢复错误（设备读取失败、单个设备不支持）记录后跳过；不可恢复错误（无输入权限、无 BLE、配对失败）打印原因与修复建议后退出，退出码 `1`。
- 状态切换打印一行：`MONITOR -> CAPTURING` / `CAPTURING -> MONITOR`，并注明原因（热键、断线、信号）。

## 12. 权限与运行环境

- `/dev/input/event*`：当前用户需在 `input` 组，或以 root 运行。README 给出 `usermod -aG input $USER` 和重新登录的说明。
- BlueZ D-Bus：普通桌面用户经 polkit 通常可用；配对被策略拦截时，README 提供把用户加入 `bluetooth` 组或用 `bluetoothctl` 预配对的备选路径。
- 不使用 udev 规则与 systemd unit；README 附一个 systemd user service 示例，供需要常驻时使用。

## 13. 测试

### 单元测试

- `test_vss.py`：逐字节对比协议文档示例；边界（长度、保留字节、type、小端 int16）。
- `test_keymap.py`：覆盖 `0x00–0x65` 中的常用键与修饰键；验证范围外忽略。
- `test_mouse.py`：累积、夹边界、分辨率换算、滚轮夹到 ±127、滚轮帧复用坐标、灵敏度。
- `test_hotkey.py`：顺序无关、左右修饰键、150ms 冷却、Esc 重置、CAPTURING 内触发。
- `test_devices.py`：用伪造的设备能力元数据验证键盘/鼠标/触摸板/电源键分类与 include/exclude。

### 集成测试

- 假 `InputSource` 产生脚本化事件 + 假 `VssWriter` 记录帧。
- 场景：进入控制→按键→退出；断线触发释放；队列积压时丢运动帧但保留键盘帧；写失败 3 次触发释放。

### 手工验收清单

- 真实 Dongle 配对成功，`FF2C` 返回 `OK`。
- 受控机 BIOS/UEFI 中键鼠可用。
- `Ctrl+Alt+Esc` 双向切换正常，热键不泄漏给受控机。
- 拔掉 Dongle 或关闭 BLE，本机键鼠立即恢复。
- `kill -9` 后本机键鼠恢复。
- 滚轮不跳左上角；长按 Ctrl 时滚轮不丢失修饰键。
- 1920×1080 下鼠标能到达四角。
- 触摸板设备被跳过且不报错。

## 14. 风险与限制

- BLE Write Without Response 无重传；弱链路下鼠标运动可能丢失，键盘完整状态帧可自愈。
- 被动监听热键时，MONITOR 下 `Ctrl+Alt+Esc` 会传给本机应用。
- 仅支持普通鼠标，不支持触摸板。
- 协议 6KRO、无媒体键、无右修饰键区分。
- Linux 桌面环境（X11/Wayland）不影响方案，因为直接读 evdev；但需要 input 组权限。
- 单连接限制来自 Dongle 固件，与客户端无关。

## 15. 验收标准

1. `cokvm-linux run` 能完成扫描、配对、认证，并进入 MONITOR。
2. `Ctrl+Alt+Esc` 进入 CAPTURING，本机键入/移动转发到受控机；再次触发恢复本机。
3. 断开 BLE（拔 dongle/关蓝牙）后 1 秒内释放 grab。
4. 单元测试与集成测试全部通过，覆盖第 13 节列出的场景。
5. README 说明依赖安装、权限配置、配对流程与已知限制。
