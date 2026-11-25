# Go2 WebRTC 局域网与公网接入

## 公网 Remote（机器狗自身 4G）

机器狗需能通过自身 4G 上网，App 的公网远程连接已开启，账号已绑定该机器狗。PC 只需能访问互联网，无需与 Go2 在同一 Wi-Fi。用户已报告设备处于 4G 状态；本脚本的公网实机握手仍待验证。

先退出旧桥接。在 PC 项目目录运行只读的状态与图像验证，将 SN 替换为 App 设备信息中的序列号：

```bash
cd ~/go2_workspace
bash shared/run_webrtc_state.sh --remote --sn '你的机器狗SN' --show-video
```

终端会询问绑定设备的 App 邮箱账号和密码，密码隐藏输入，不写入文件或命令行。当前社区驱动使用邮箱密码登录接口，不支持仅手机号/短信验证码登录。中国区默认 --region cn，海外账号使用 --region global；可用 --username 指定邮箱。不要在聊天中提供密码。

收到状态和图像后，退出并增加 --control 启动键盘转发：

```bash
bash shared/run_webrtc_state.sh --remote --sn '你的机器狗SN' --control --show-video
```

另开终端运行下文相同的 ROS 2 环境与键盘命令。--video、--lidar、--duration 同样适用于公网模式。Remote 使用驱动的云信令及 ICE/TURN 流程，不限制本机网卡；不能与 --ip 或 --local-ip 混用，也不使用 wwan0 的私网 IP 作为目标。现有 0.8 秒指令超时停步逻辑保留；网络完全中断时停止指令无法保证抵达，机器狗端停步行为仍待实测。

实现基于已安装社区驱动 2.2.0 的 Remote 分支，并非官方 ROS 2 公网 DDS 接口。云登录、区域和设备权限兼容性需通过绑定账号实测。

## 局域网 LocalSTA

PC 与 Go2 原厂无线系统连接同一热点。本次验证 IP 为 10.186.248.47，PC Wi-Fi 为 10.186.248.173。热点重新分配地址时修改 --ip。

当前已准备的运行环境是项目内 .work/webrtc-venv（系统 Python 3.10），驱动 unitree_webrtc_connect 2.2.0，来源提交 e0abc5780761539eff89a382a79319e5cf6ad1f4。运行入口同时定位 .work/webrtc-system-libs 内的 PortAudio。入口加载 Humble 和宇树消息包，用 ROS_LOCALHOST_ONLY=1 发布 PC 本地话题。ICE 候选限制为访问目标 IP 的本机地址，可通过 --local-ip 显式指定 Wi-Fi IP。

## 状态、图像和点云

在 PC 的项目根运行：

```bash
bash shared/run_webrtc_state.sh --ip 10.186.248.47 --video --lidar
```

要在 PC 弹窗实时看相机，可运行：

```bash
bash shared/run_webrtc_state.sh --ip 10.186.248.47 --control --show-video
```

--show-video 自动启用图像读取，同时继续发布 /go2/webrtc/image。图像解码后缩至 640×360，预览窗口初始大小也是 640×360。显示在独立进程运行，避免 GUI 阻塞网络收包。按 Esc 或关闭图像窗口结束预览，桥接与键盘转发继续运行。原有桥接运行时先停止键盘移动、退出键盘，再用 Ctrl+C 结束旧桥接，之后以新命令启动并重新打开键盘节点。

只有运动状态时省略 --video --lidar。Ctrl+C 断开会话。--duration 8 表示采集 8 秒后退出。

| PC 本地 ROS 2 话题 | 消息类型 | 数据 |
| --- | --- | --- |
| /go2/webrtc/sportmodestate | unitree_go/msg/SportModeState | 保留原厂状态字段和源时间戳 |
| /go2/webrtc/image | sensor_msgs/msg/Image | 640×360 rgb8 相机图像，PC 接收时间戳 |
| /go2/webrtc/points | sensor_msgs/msg/PointCloud2 | 无线体素地图解码的 XYZ 点，PC 接收时间戳 |

图像的 frame_id 为 go2_webrtc_camera。点云使用源 frame_id，本次为 odom，源数据缺失时使用 go2_webrtc_voxel。相机标定和 TF 尚未接入，体素点云的坐标和导航适用性待进一步验证。

另开 PC 终端订阅：

```bash
cd ~/go2_workspace
source /opt/ros/humble/setup.bash
source unitree_ros2/cyclonedds_ws/install/local_setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_LOCALHOST_ONLY=1
unset CYCLONEDDS_URI
ros2 topic echo /go2/webrtc/sportmodestate --once
```

## 键盘

先启动带控制转发的桥接：

```bash
bash shared/run_webrtc_state.sh --ip 10.186.248.47 --control
```

在另一个 PC 终端运行，启动脚本会自动加载 Humble 与宇树消息包：

```bash
bash shared/run_webrtc_keyboard.sh --robot
```

键盘的 1/2/3/4 对应 StandUp、BalanceStand、StandDown、Damp，W/S 前后 0.35 m/s，A/D 转向 1.0 rad/s，空格 StopMove，Q 退出。桥接只接受这些 API 和该速度范围。收到 Move 后超过 0.8 秒没有新的指令且连接仍可用时，桥接发送 StopMove。网络断开后无法保证停止请求抵达，Go2 端超时停步行为仍待验证。响应 JSON 发布到 /go2/webrtc/sport/response。

--control 可和 --video --lidar 合用。用户已确认拔掉有线后的无线键盘移动成功；最新 1.0 rad/s 转向待现场验证。通过单独的无线请求话题避免同一请求同时进入有线与无线链路。

## 运行环境来源

本次用系统 Python 创建启用系统包的项目虚拟环境。安装了 aiortc 1.15.0、curl_cffi 0.17.0、wasmtime 50.0.1、sounddevice 0.5.6、numpy 1.26.4，复用已有 pycryptodome、requests 和 lz4。社区驱动从上述提交以 --no-deps 安装，实际入口使用的依赖已验证。PortAudio 19.6.0-1.1 的 Ubuntu deb 解包到 .work/webrtc-system-libs/extracted，并补 libportaudio.so 符号链接。详细实机结果见 EXP-0003。
