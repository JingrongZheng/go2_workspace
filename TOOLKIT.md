# 共享代码与工具索引

- 实机Go2 EDU名义几何：`shared/dddmr/real/go2_nominal_geometry.json`，从宇树官方URDF提取base/radar/imu安装关系，含EDU尺寸、来源摘要和未验证条件；只作参数依据，不能直接作为已标定启动配置。说明见`docs/navigation/go2-geometry.md`，静态证据EXP-0019，独立于仿真入口。

真实代码放在项目级 shared/ 或已有 src/包目录，本文件只记录模块路径和导入/调用方式。不要把共享实现留在某个 Experiment 下，也不要在这里用 Markdown 代替代码。
写实验前先查已有的数据处理、评价、绘图和验证入口；实验只保留输入、参数、共享调用与产物保存。
清理实验不能删除被其他实验或项目代码使用的共享能力。

- WebRTC 键盘启动入口：`bash shared/run_webrtc_keyboard.sh --robot`，自动加载 Humble 与宇树消息包，绑定 PC 本地无线请求话题；适用于 LocalSTA 和 Remote。省略 --robot 为预览，不发送实机请求。

- [Go2 WebRTC 桥接](shared/go2_webrtc.md)。实现位于 shared/go2_webrtc_state.py，通过 shared/run_webrtc_state.sh 启动：--ip 为局域网，--remote --sn 为公网（本机交互输入绑定账号邮箱与密码，默认中国区）。--show-video 使用 shared/go2_camera_viewer.py 独立显示 640×360 相机画面。在 PC 发布原厂无线状态、相机图像和体素点云，可用 --control 接收独立键盘请求话题。公网实机连接待验证；入口和环境见链接。

- 有线点云只读检测：`bash shared/check_wired_lidar.sh --duration 15`。自动加载 ROS 环境并绑定 `GO2_IFACE`（默认 enp2s0）、DDS 域 0，动态订阅发现的 PointCloud2，报告帧数、观察频率、字段和数据布局；实现 shared/probe_wired_lidar.py。收到点云不等于已确认 XT16 来源。

- D435i 双视频录制：PC执行 `bash shared/record_realsense.sh --host unitree@192.168.110.87`（以当前无线IP为准），本地输入SSH密码，显示并保存 recordings/<时间>/rgb.mp4、depth.mp4，Q/Esc/Ctrl+C结束。板端shared/realsense_sender.cpp使用已有SDK及libjpeg，640×360@15、JPEG质量75，深度固定0.2–5m伪彩；PC写MP4，每5秒报告实际接收fps与Mbps。无需ROS。已通过板端编译、真实相机及78对帧双MP4预检（该预检走有线）；正式WiFi录制在EXP-0008跟踪。

- 机载 SSH 会话入口：`bash shared/connect_go2_ssh.sh`，用户在 PC 终端完成密码认证，私有控制套接字位于 .work/ssh-control/go2.sock，空闲保留30分钟；后续 `ssh -S "$PWD/.work/ssh-control/go2.sock" unitree_go2 <命令>` 复用认证，不保存密码。关闭：`ssh -S "$PWD/.work/ssh-control/go2.sock" -O exit unitree_go2`。

- 新 Realtek USB 网卡驱动离线编译：在 PC 执行 `bash shared/build_go2_usb_wifi.sh`，复用 SSH 将 .work/usb-wifi-kit.tar.gz 传到板端 ~/go2-wifi-repair，检查完整头文件和编译工具，以 ARCH=arm64 编译 88x2cu；仅编译，不安装/加载/解绑。来源提交和检查命令见 EXP-0007；日志 experiments/EXP-0007/driver-build.log。

- 新Realtek USB WiFi持久安装：`shared/install_go2_usb_wifi.sh`，固定适用于aarch64/5.10.104-tegra与0bda:c812；在板端sudo执行并传入已编译88x2cu.ko绝对路径。安装模块、禁用驱动省电、开机加载及udev触发的局部绑定服务；只接管目标网卡的option接口，不全局拉黑option。真实热插拔及重启恢复待验证，见EXP-0007。

- XT16机载驱动只读清单：`shared/inspect_xt16_driver.sh` 在拓展坞执行，不需要启动雷达驱动或SLAM。检查包、文件路径、进程、服务、UDP监听和日志；输出缺失不能单独证明未安装，需结合自定义工作空间/容器核查。见EXP-0009。

- 已定位XT16厂商驱动：板端 `/unitree/module/graph_pid_ws` 的 `hesai_lidar 0.9.2`（Foxy），加载厂商工作空间后入口 `ros2 launch hesai_lidar hesai_lidar_launch.py`，单独雷达节点。参数/启动/2368监听已验证，真实点云待上电；不能替换成新版hesai_ros_driver命令，也不以0_unitree_slam.sh代替独立驱动测试。证据EXP-0009。SSH helper现在清理check失败后的本项目陈旧socket并使用keepalive。

- 板端雷达网口元数据抓取：`shared/capture_lidar_ethernet.py [eth10] [25]`，Linux上需sudo/CAP_NET_RAW，时间上限60秒；记录ARP/UDP源地址与计数，不记录载荷，排除已识别运控.161高频UDP。socket级混杂模式随退出撤销。EXP-0009已板端实测。

- 受限雷达ARP地址探测：`shared/probe_lidar_arp.py`，在板端sudo运行，固定eth10源192.168.123.18，仅机器人123网段及官方默认192.168.1.201；不改地址。需结合VLAN/分段边界解读。实测记录EXP-0009。

- XT16新版官方驱动独立对照：板端 `~/go2-lidar-diagnostic/hesai_v2_ws`，包 `hesai_ros_driver`，运行ROS/SDK V2.0.12；固定源码与配置、对照结果见EXP-0010。需只加载Foxy及此独立工作空间，配置 `config_xt16_compare.yaml` 为纯接收；厂商旧驱动保持在/unitree。已编译及端口监听验证，尚无有效点云，不能宣称升级修复雷达。

- 用户指定官方禾赛驱动启动入口：`shared/run_xt16_official_onboard.sh` 与 `shared/config/xt16_official.yaml`。已部署板端 `bash ~/go2-lidar-diagnostic/run_xt16_official.sh`，加载Foxy+官方hesai_v2_ws，PTC启用、.20/2368，输出/lidar_points；默认域0，不改变原厂开机配置。版本启动打印已核对，PTC/点云未通过，短测需timeout兜底停止。见EXP-0010。

- XT16正式域0启动修复：入口需加载机载 `~/cyclonedds_ws/install/setup.bash` 的配套RMW、`/usr/local/lib` DDS库，使用 `shared/config/xt16_cyclonedds.xml` 绑定实际eth10。已部署独立XML，不改机载旧eth0 XML。系统Fast DDS域0可在无雷达的最小节点复现bad_alloc，匹配环境修复已实测。见EXP-0010日志；不能仅设置RMW而漏加载配套库。


- [本地DDDMR Docker与运行说明](shared/dddmr/README.md)：`build_navigation.sh`/`build_simulation.sh`从完整固定版本归档构建；`run_local.sh simulation|navigation`启动，随后`run_local.sh initialize`仅为配套演示地图从Gazebo里程计提供MCL初始位姿；实机不用此初始化。支持`DDDMR_DETACH=1`。只读用户源码、NVIDIA GLX、域83/localhost、专用Xauthority、标准RViz停靠布局。两个镜像/25包/Gazebo/RViz/跨容器点云/平地目标导航已实测通过。`probe_runtime.py --duration 15`仅观测时钟、点云、里程计、TF、路径与速度；`initialize_demo_pose.py`仅一次发布仿真初始位姿。证据EXP-0015及experiments/EXP-0015。

- DDDMR重复启动修复（EXP-0016）：同一simulation/navigation启动命令现在复用正在运行的容器；界面已关时仅重开gzclient/rviz2。容器停止或镜像不符时明确提示，不自动删除。已实测恢复窗口及重复调用不新增实例。

- [L1＋IMU经WiFi的PC端实机部署计划](docs/navigation/real-deployment.md)：真实输入合同、原生直连/机载仅转发两条路径、Point-LIO/FAST-LIO2候选、DDDMR适配项与R0–R7验收。当前为计划，不是已验证实机启动脚本；仿真已关闭。

- Go2 EDU 实机软件入口见 [实机 README](shared/dddmr/real/README.md)。包含 ROS 2 Humble Docker 中的 L2 Point-LIO、机体里程计换算、原始数据录包和 RViz。DDDMR 映射和定位的 Cuboid 用 `shared/dddmr/real/configure_dddmr.py` 生成，EDU 站立尺寸 0.70×0.31×0.40 m，碰撞框默认按 1.1 倍。详见 EXP-0020。

- Go2 原始传感器 WiFi 转发用 `shared/dddmr/real/run_sensor_relay.sh`。机载 eth10 订阅两路传感器，PC 经 WiFi SSH 接收后在本机域 84 发布 `/go2/relay/cloud` 与 `/go2/relay/imu`，保留采样时间。PC 拔网线后的独立录包已验证，见 EXP-0021 与 [实机 README](shared/dddmr/real/README.md)。

- EXP-0024 实机修正：`run_sensor_relay.sh --include-chassis-imu` 同时转发 L2 点云、L2 IMU 与完整机体 IMU，传输使用 zlib，机体时间间隔来自 LowState 原生毫秒 tick。`GO2_IMU_SOURCE=chassis run_point_lio.sh ...` 选择 `point_lio_chassis.launch.py`，物理 radar 与固件发布坐标分开。有效滑动窗口、多帧初始化及可重复源码修正见 `patch_point_lio.py`；本机校准见 `go2_published_cloud_geometry.json`。新录包完整静止检查通过，走动数据和动态结果见 EXP-0024；不启动任何控制节点。

- EXP-0025 L2实机建图：`shared/dddmr/real/prepare_l2_mapping.py` 生成独立参数，`mapping_cloud.py` 按逐点时间与LIO轨迹去畸变并运动补偿累积，`go2_l2_mapping.launch.py` 只运行建图。`run_mapping_replay.sh BAG YAML GROUND_Z NEW_OUTPUT` 在一个无网络容器中回放、建图、保存和检查完整资产；`run_mapping.sh wifi ...` 为现场只读建图入口。默认L2配置见 `config/l2_mapping_lab.yaml`。使用真实第二轮走动录包生成24关键帧地图并通过作者地图服务器重载；证据 `experiments/EXP-0025/`，不等于重定位/自主导航通过。

- 当前局域网PC键盘：`bash shared/run_wifi_keyboard.sh --robot`，PC复用EXP-0002键位，经现有WiFi SSH在机载eth10/域0转官方高层Request。默认0.35m/s与1rad/s；不依赖建图ROS域。`--check`只读，省略--robot为无DDS发布预览。机载独立消息包及接收器已部署，重新安装用`setup_wifi_keyboard.sh`；说明[WiFi键盘](shared/go2_wifi_keyboard.md)。只读订阅/序列化与禁用发布的协议测试通过，代理没有发运动请求；真实按键待用户，见EXP-0026。

- EXP-0027：WiFi建图断流已定位为USB网卡接口振动松脱；省电关闭已只读核验。转发器超时提示补充保存地图/新会话要求，不跨缺失IMU自动续图；详见实机README的断流章节。

- 实机统一建图：`shared/dddmr/real/run_live_mapping.sh NEW_SESSION_DIRECTORY [GROUND_Z]` 在单个PC Docker中通过`go2_live_mapping.launch.py`启动Point-LIO（机体IMU）、TF/点云适配和DDDMR；不含控制。采集与RViz独立，有线采集用relay的`--host 192.168.123.18`，无线用机载当前WiFi IP。旧分开入口保留排查，勿同时启动；`run_mapping_replay.sh`复用同一launch，输出stack.log。见EXP-0028及实机README。

- 离线同步位姿图回环优化：`PYTHONNOUSERSITE=1 /usr/bin/python3 shared/dddmr/real/optimize_pose_graph.py [--level-ground] INPUT_MAP_DIR NEW_OUTPUT_DIR`，规避上游在线 `lego_loam_node` 并发回环段错误（见 `knowledge/dddmr-loop-closure-race-bug.md`），对已保存 DDDMR 地图自动做局部子图 3D ICP 回环检测与稀疏 LM SE(3) 全局优化，可选 `--level-ground` 做单一刚体水平归平并重新拼接完整资产，不覆盖原图；输出可直接由 `./go2 view-map` 与 `dddmr_pg_map_server_node` 加载。见 EXP-0034。

- 独立急停与平衡站立终端：`./go2 estop [wired|wifi] [--robot]`（实现 `shared/go2_estop.py`、`shared/run_estop.sh`），复用已部署的机载 `go2_wifi_control_source.py` 无需重新部署。启动后预连接待命且不发送指令；按空格或回车立即写入 `.work/estop.lock` 切断 `cmd-bridge` 并发 `StopMove (1003) + BalanceStand (1002)`（5 Hz 持续锁止直到按 `R` 释放），数字键沿用 `keyboard` 风格：`1` 平滑 `StandUp (1004)`、`2` `StopMove + BalanceStand (1002)`、`3` 锁死速度桥 + 平滑 `StandDown (1005)`，`Q` 退出；省略 `--robot` 为干跑预览，`--check` 只读检查。

- R5 自主导航速度桥：`./go2 cmd-bridge [wired|wifi] [--robot] [--max-vx 0.35] [--max-wz 0.8]`（实现 `shared/go2_cmd_vel_bridge.py`、`shared/run_cmd_vel_bridge.sh`），将 PC 域 84 的 `/cmd_vel` 限幅并按 10 Hz 经 SSH 转发至已部署的机载 `go2_wifi_control_source.py`（继承机载 `0.4s` 新鲜度校验、`0.8s` 看门狗与断链自动 `StopMove`，PC 侧额外增加 `0.5s` 超时停步、死区滤波与退出 `StopMove`）。省略 `--robot` 为干跑预览，建议与 `./go2 estop --robot` 同开。见 EXP-0037。

- D435i 对齐原始 RGB-D 关键帧采集与本机 3DGS 重建流水线（`shared/gs3d/`，收口于 `./go2 rgbd-record` / `gs-build` / `gs-train` / `gs-view`）：机载 `rgbd_keyframe_sender.cpp`（`rs2::align` 848×480 RGB + 无损 Z16 深度 + 出厂内参，默认 2.5 Hz）经 SSH 传回 PC，`record_rgbd_keyframes.py` 落盘清晰度指标并可选同步域 84 `/mcl_pose`；`align_colmap_to_nav.py` 完成 COLMAP→DDDMR `map` Sim(3) 对齐与深度初始点云反投影；`train_gsplat.py` 在 `go2-3dgs:latest` Docker 镜像（RTX 3060 6GB，`gsplat` + 深度监督 + 35 万高斯上限）输出标准 `.ply`；`view_gsplat.py` 启动浏览器 `viser` 交互预览。见 EXP-0038。

- 工作区统一启动入口：`./go2`（位于 `go2_workspace` 根目录，自动按自身路径解析工作区根目录，不硬编码绝对路径）。收口 `ssh`、`relay`、`map`、`localize`、`nav-dryrun`、`rviz`（`mapping|l2|localize|nav`）、`record`、`save-map`、`keyboard`、`estop`、`replay`、`view-map`、`help` 子命令，支持 `wired` / `wifi` 链路切换与环境变量覆盖；`connect_go2_ssh.sh` 改为直连 `unitree@<IP>` 不依赖 `~/.ssh/config`，键盘驱动沉淀至 `shared/go2_keyboard_control.py`（解除对 `experiments/EXP-0002` 的耦合）。`keyboard` 与 `estop` 默认预览，仅显式 `--robot` 才允许用户实机发送；`view-map` 通过 `shared/dddmr/real/run_view_map.sh` 在 RViz2 中 3D 显示保存地图；`localize` 启动 R3 纯 3D MCL 重定位；`nav-dryrun` 启动 R3+R4 合并干跑（MCL + A\* 全局规划 + P2P 局部规划 + Cuboid + 只读 `/cmd_vel` 审计，无真机速度桥）。见 [实机 README](shared/dddmr/real/README.md)、EXP-0029、EXP-0032、EXP-0035 与 EXP-0036。

- 对话音频共享实现：`shared/audio/xfyun_tts.py`、`webrtc_audio.py`、`xfyun_duplex.py`。2026-11-27 按用户要求移除统一入口的 `speak` 与 `voice-train`（用户称 train-voice）命令、帮助及派发函数；保留对话依赖的合成、WebRTC 播放与既有音色配置。音色训练和独立播报不再作为 `./go2` 用户入口提供。当前对话用 `./go2 ask`，历史实验的旧命令仅为当时证据。

- 文字流式对话（EXP-0042）：`./go2 chat --ip <原厂主板IP> --voice mambo`；PC 流式试听用 `--local-preview`，只检查大模型用 `--no-audio`。实现 `shared/audio/streaming_dialogue.py`、`xfyun_duplex.py`、`run_dialogue.sh`，复用既有 WebRTC 环境、讯飞配置与 PCM 播放轨道。Kimi 官方配置在忽略的 `.work/dialogue.env`：`LLM_BASE_URL=https://api.moonshot.cn/v1`、`LLM_MODEL=kimi-k3.1-pro-highspeed`、`LLM_REASONING_EFFORT=low`、`LLM_API_KEY`。默认 `--tts-mode sentences` 为大模型持续生成、按短句送讯飞、各段内音频流式播放；`--tts-mode duplex` 为单会话双向流式试验路径，本次真实接口有缓冲，不能保证更低延迟。支持多轮记忆、`/reset`、`/quit`；思考字段仅在内存中按 Kimi Preserved Thinking 回传，不显示不播报。说明与验证边界见 `shared/audio/README.md`。用户已确认基础真机扬声器正常，当前对话端到端实机联调尚待密钥和当前 IP。

- 机载独立对话（EXP-0043，当前部署目标）：机载代码 `shared/audio/onboard_dialogue.py`，只监听 127.0.0.1:8765，通过 `onboard_request.py` 接受 `/ask` 任务。PC `./go2 ask "问题"` 仅经 SSH 发送文字并查看输出，`--submit-only` 提交后立即退出；模型、TTS、上下文和播放均在机载执行，任务不依赖提交连接。部署到 `unitree@192.168.123.18:~/go2-dialogue`：`python3 shared/audio/deploy_onboard_dialogue.py`，离线 ARM64 轮子在 `.work/onboard-dialogue/wheels`；`--code-only` 更新源码。机载用 `manage_onboard_dialogue.sh start|stop|status` 管理独立 systemd 用户服务，依赖隔离在 `.venv`，不修改系统 Python。内部 WebRTC 连接原厂主板 `192.168.123.161`。当前联网验收受 Wi-Fi 与密钥限制，用户要求忽略 Wi-Fi，详见 `shared/audio/ONBOARD.md`。

- 2026-11-27 机载对话实测更新：`./go2 ask "问题"` 已通过真实云端与扬声器闭环，用户确认声音正常。实际模型为账号可用的 `kimi-k3.1-pro`/low（highspeed 返回404），音色 mambo。密钥已写机载配置600权限；安全传入工具 `python3 shared/audio/configure_onboard_key.py --key-file <本机密钥文件>` 经SSH stdin原子写入，不输出密钥。前述“待 Wi-Fi/Key”的状态由本条替代。当前短句流水线不要求等完整回复，但极短回复可能在文字结束后才收到首包音频。

- 无线提问入口修复（EXP-0043）：`./go2 ask --host 192.168.110.87 "问题"` 自动选 `.work/ssh-control/go2-wifi.sock`，有线地址选 `go2.sock`；`--socket` 可显式覆盖，未知地址不复用已知主机 socket。无线登录已建立仍 Permission denied 的固定有线 socket 问题已修复，实测 PC .110.120 → 机载 .110.87:22 的健康查询通过。

- 对话音质修正（EXP-0044）：`StreamingPcmResampler` 使用持久 PyAV 带限滤波器，`RobotSink` 连续拼接48kHz输出，仅整轮最后帧补零；替代每20ms重建线性插值产生的高频镜像。合成按句末标点（最长80字）发送，不再在逗号/冒号处切断上下文。13项测试通过，已部署机载并用真实 Kimi 回复实测，用户确认“噪声完全消失”。对照素材和分析见 `experiments/EXP-0044/`；不宣称已唯一证明原噪声根因。保持流式播放，不切到用户反馈语速异常的 megaphone 路径。

2026-11-27 代码清理：独立训练/播报源码与包装脚本已删除（xfyun_clone_train.py、go2_audio_play.py、run_clone_train.sh、run_audio_play.sh），旧compare_audio_paths.py也已移除。当前共享音轨模块为shared/audio/webrtc_audio.py，xfyun_tts.py仅保留对话所需的配置/鉴权/流式合成核心，已删除训练音频处理、测试音和独立CLI。历史实验中的旧路径/命令仅描述当时的证据。部署器会清除机载上述退役文件及对应缓存，不动密钥、音色和实验产物。两端各13项测试通过，机载对话服务已恢复。
