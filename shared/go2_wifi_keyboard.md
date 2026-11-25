# 当前局域网的 PC 键盘控制

当前连接使用 PC→WiFi/SSH→机载小电脑→内部eth10 DDS→Go2高层运动接口。PC运行旧实验的键盘输入逻辑，机载端仅将新鲜按键请求发布为官方 `unitree_api/msg/Request`；建图、Point-LIO和RViz仍在PC。原WebRTC入口独立保留。

## 运行

当前机器的独立消息工作空间已构建、接收程序已部署。沿用已认证的 `.work/ssh-control/go2-wifi-new.sock`，小电脑IP默认192.168.110.87。

```bash
# 在工作区根目录执行（推荐统一入口，wired / wifi 自动匹配默认 IP 与 socket）
./go2 keyboard wifi --check
./go2 keyboard wifi --robot
# 有线模式：
./go2 keyboard wired --robot

# 或直接调用底层脚本：
bash shared/run_wifi_keyboard.sh --check
bash shared/run_wifi_keyboard.sh --robot
```

省略 `--robot` 为预览，接收端禁用DDS发布。`--host` 与 `--socket` 可覆盖默认连接。启动脚本自动加载Humble和PC宇树消息包，键盘不依赖建图ROS域；机载DDS明确使用域0并绑定eth10。

| 按键 | 操作 |
|---|---|
| W/S | 前后0.35 m/s，沿用此前实测起步速度 |
| A/D | 左右转向±1.0 rad/s |
| 空格 | StopMove |
| Q | 退出；若正在移动先发送StopMove |
| 1 | StandUp |
| 2 | BalanceStand |
| 3 | StandDown |
| 4 | Damp，与主动趴下分开 |

保持该终端有焦点。停止实验时先空格、停稳、Q退出键盘，再停止录包、保存地图，最后停止建图/Point-LIO/传感器转发。

## 传输与验证边界

- 新入口复用 `shared/go2_keyboard_control.py`（源自 EXP-0002）的 drive、按键和速度，不更改原WebRTC启动器。
- 建立连接只做时钟握手与DDS订阅发现，未收到按键不发送姿态、移动或停止请求。
- PC请求携带时间戳，以SSH时钟往返估计转换到机载时钟；大于0.4秒的旧请求丢弃。不会自动重连继续旧命令。
- 机载接收端在活动Move超过0.8秒无新请求时尝试StopMove；EOF/断开和进程信号也在活动移动时尝试停步。这些逻辑在禁用DDS发布的预览模式验证过；真实机器人停车延时和断链反应仍由用户现场验证。
- 本次只读检查发现 `/api/sport/request` 有1个订阅者、类型unitree_api/msg/Request，空请求可序列化为48字节。所有代理测试实际控制消息发送数为0。证据见 EXP-0026。

## 重新部署

机器人系统重装或接收程序更新后，可在PC执行：

```bash
bash shared/setup_wifi_keyboard.sh
```

它复制本机官方unitree_api的8份消息定义到 `~/go2-keyboard-control/ws`，使用Foxy构建，只省略独立的可选Connext生成步骤；不改消息定义、不改系统自启。所有文件位于unitree用户的独立目录。部署本身不发送运动指令。
