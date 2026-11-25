# Go2 EDU 实机准备与标准启动

## 推荐统一入口（`./go2`，零硬编码路径）

所有实机日常操作均已收口到工作区根目录的 `./go2`，脚本自动按自身位置解析工作区路径，整个 `go2_workspace` 迁移到其他目录或主机后可直接使用（无需 `~/.ssh/config` 别名；仅当宿主机使用 PC 键盘且迁移后 `unitree_ros2/cyclonedds_ws/install` 路径失效时，在 `unitree_ros2/cyclonedds_ws` 重新执行一次 `colcon build` 即可）。

```bash
# 1. 建立可复用 SSH 认证（有线 wired 默认 192.168.123.18；无线 wifi 默认 192.168.110.87，可用 --host 覆盖）
./go2 ssh wired

# 2. 终端 1：启动只读传感器转发（L2 点云 + L2 IMU + 机体 IMU，自动校时，ROS 域 84）
./go2 relay wired

# 3. 终端 2：启动单 Docker 统一建图（Point-LIO + 机体 TF + 运动补偿适配 + DDDMR，不含控制）
./go2 map
# 或指定新会话目录：./go2 map experiments/EXP-0028/live-wired-$(date +%Y%m%d-%H%M%S)

# 4. 终端 3：打开 RViz（自动加载 Humble、域 84 与 go2_mapping.rviz）
./go2 rviz

# 5. 终端 4（可选）：录制三路原始传感器 bag（默认输出 .work/sessions/bag-<时间>）
./go2 record

# 6. 终端 5（可选）：PC 键盘控制（省略 --robot 为预览，不发实机指令；--check 为只读检查）
./go2 keyboard wired --robot

# 7. 扫描结束：先空格停稳、Q 退出键盘，Ctrl+C 停录包并落盘，再保存地图，最后 Ctrl+C 停止建图和转发
./go2 save-map
```

- 切换到 WiFi 时，只需将上述 `wired` 改为 `wifi`（默认 IP `192.168.110.87`，可用 `--host <IP>` 或环境变量 `GO2_WIFI_HOST` 覆盖）。
- 离线回放录包建图：`./go2 replay experiments/EXP-0024/motion-trial-02 [输出目录]`。
- 运行 `./go2 help` 查看全部子命令和环境变量覆盖项。

---

## 技术细节与历史参考入口

### 2026-11-25 当前已验证的传感器入口

当前机体坐标已通过静止验证的组合是 **L2 发布点云＋机体 IMU**，使用 `point_lio_chassis.launch.py`；不能把 L2 内置 IMU 参考入口的机体方向当作已验证。WiFi 采集只读，不启动控制或导航。上游原始平面拟合保留，未采用试验性的恒定 IMU、时间量化、冻结地图或关键帧开关。

```bash
# 终端 1：PC，只读采集；socket 需为当前已认证的无线 SSH
PYTHONNOUSERSITE=1 bash shared/dddmr/real/run_sensor_relay.sh \
  --socket "$PWD/.work/ssh-control/go2-wifi-new.sock" --include-chassis-imu

# 终端 2：PC Docker，只估计位姿，不发送控制
GO2_IMU_SOURCE=chassis ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 \
  bash shared/dddmr/real/run_point_lio.sh wifi /go2/relay/cloud /go2/relay/chassis_imu
```

Docker 命令需在当前用户有 Docker 权限的终端执行；本次代理运行使用 `sg docker -c '...'`。初始积累 20000 个降采样点，需先由用户使机器人站稳并保持静止数秒，等出现连续里程计后再操控。第三路 `/go2/relay/chassis_imu` 来自 `/lowstate`，保留完整加速度与角速度；原始 L2 IMU 仍发布在 `/go2/relay/imu`。机体时间间隔使用原生毫秒 tick，epoch 按机载接收时延估计并与 L2 共同校时，属于软件对时，不能称为硬件同步。tick 重置时退出，重新启动校准。

局部地图边长设为 1000 m、探测范围 100 m，以满足上游滑动窗口 `cube_side_length > 3 * mapping.det_range`。这是内部窗口参数，不表示真实雷达能测 1000 m。原默认 200/100 不满足条件，静止也反复移动/裁剪窗口，导致严重漂移。多帧初始化与 `mapping.plane_thr=0.03` 用于当前稀疏点云。构建器自动应用 `patch_point_lio.py`：修正 reserve 后索引、缓存清空、时间精度，并拒绝无效窗口组合。

坐标定义见 `docs/navigation/current-tf-chain.md`。`go2_published_cloud_geometry.json` 是本机发布点云相对机体的重复实测变换；URDF 的物理 `radar` 安装位置仍独立保留，不能把两个 frame 混成一个或重复旋转。

静止新录包的完整共享入口检查见 `experiments/EXP-0024/shared-profile-check.json`：X/Y/Z 位置跨度约 5/6/19 mm、机体 Z 朝上、地面倾角 0.44°、完整 TF 可查询。动态记录和验收以 EXP-0024 最新 Results 为准。下文保留的 L2 内部 IMU 启动方式是参考基线。


PC 上以 ROS 2 Humble Docker 运行 Point-LIO，输入为同一只 L2 的原始 PointCloud2 和内置 IMU。构建脚本复用现有 DDDMR 基础镜像，固定 Point-LIO ROS 2 提交 a8e2d0d5090af97ead8dd4fac3d37cf3dbb33ff7。实机启动文件加载该提交的 L2 配置，并用官方模型的名义外参生成 TF。里程计适配器将 IMU 位姿和速度换算到机体原点，发布 /odom。

- 构建用 `bash shared/dddmr/real/build_point_lio.sh`。
- 本机回放用 `bash shared/dddmr/real/run_point_lio.sh offline RAW_CLOUD INTERNAL_IMU BAG_DIRECTORY`。两个话题名均为录包中的绝对话题名，同一个容器内回放和估计。
- WiFi 输入用 `ROS_DOMAIN_ID=84 bash shared/dddmr/real/run_point_lio.sh wifi RAW_CLOUD INTERNAL_IMU`。按数据发布端指定相同的 DDS 域。原始话题、IMU QoS 和采样时间单位需从实机确认。
- 录包用 `ROS_DOMAIN_ID=84 bash shared/dddmr/real/record_l2.sh BAG_DIRECTORY RAW_CLOUD INTERNAL_IMU`。与实际数据端使用同一域。
- WiFi 模式在 PC 用 `ROS_DOMAIN_ID=84 rviz2 -d shared/dddmr/real/go2_l2.rviz` 查看点云、TF 和轨迹。

## Cuboid

DDDMR 把八个角点随候选位姿移动，并判断障碍点是否进入盒内。EDU 站立外形为 0.70 × 0.31 × 0.40 m。碰撞框按用户指定的 1.1 倍配置为 0.770 × 0.341 × 0.440 m。前后、左右暂按机体原点对称，下沿从地面起算，多出的 4 cm 高度放在上沿。DDDMR 地图的 `inflation_radius` 控制独立的代价场，生成器保留上游数值。

`configure_dddmr.py` 接收现有映射或定位 YAML，输出替换全部八角点配置的新 YAML。默认比例为 1.1，纯外形参考用 `--scale 1`。用 `--ground-z` 指定站立时地面在规划器 base_link 中的 z 坐标。需要修正平面中心时传入 `--center-x` 和 `--center-y`。以地面为参考的输出可用 `--ground-z 0` 生成。

DDDMR 建图启动文件为 `go2_mapping.launch.py`，输入为经过核对的映射 YAML 和原始雷达话题。生成工具替换 Cuboid，设为实时时钟，关闭 DDDMR 的外部里程计 TF 重发，并清空演示地图路径。定位配置可用 `--pose-graph-dir` 填入实机地图路径。DDDMR 点云投影和地面分割仍需根据 L2 实测数据设置，建图模式用 `ground_z` 定位 base_footprint。
 
使用 `bash shared/dddmr/real/run_mapping.sh wifi PARAMETERS_YAML RAW_CLOUD GROUND_Z` 启动建图模块，DDS 域与 Point-LIO 一致。地图保存服务为 `/save_mapped_point_cloud`，输出位于 `.work/dddmr-real/maps/` 或 `DDDMR_REAL_MAPS` 指定的目录。空输入启动检查中 DDDMR 建图进程能读取参数并启动，退出由 ROS 2 launch 超时结束。首次实机验证从静止数据录包、检查逐点时间与 IMU 后开始，已完成的文件检查不构成实机导航验收。

## 机载电脑经 WiFi 转发原始传感器

机载端在 eth10 上只订阅 `/utlidar/cloud` 和 `/utlidar/imu`，通过现有局域网向 PC 的 SSH 会话发送数据。PC 端以 ROS 2 域 84 发布本机话题 `/go2/relay/cloud` 和 `/go2/relay/imu`，保留原始字段、坐标系和逐点时间。机载采集程序随 SSH 会话运行和退出。

在项目根目录用 `bash shared/dddmr/real/run_sensor_relay.sh --socket "$PWD/.work/ssh-control/go2-wifi.sock"` 复用已认证连接，Ctrl+C 结束。无现成套接字时，从本机交互终端省略 `--socket` 并输入 SSH 密码。以 `--host` 指定机载当前 WiFi IPv4，默认 192.168.110.87。PC 订阅者须设置 `ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1`。

可用 `ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 bash shared/dddmr/real/record_l2.sh BAG_DIRECTORY /go2/relay/cloud /go2/relay/imu` 录包。EXP-0021 在 PC 有线接口断开时收到 202 帧点云和 3245 条 IMU，独立录包计数相同。实机 TF 与时钟仍按 EXP-0018 的检查结果处理。机器狗由用户操作。

转发默认自动校时，见 EXP-0023。每次启动经 SSH 比对 PC 和机载系统时钟，再用机载端收到的 IMU 样本估计传感器时钟，一次算出给两路消息头共用的偏移。点云中每个点的相对时间保持原样。运行时如果源时间戳失去单调性，或时钟及数据新鲜度明显偏离，转发会报错退出。重新运行会重新测量。原始采集可用 `--raw-stamps`，已知偏移可用 `--stamp-offset-seconds` 手动覆盖，两者均关闭自动校时。

使用 PC 转发的话题时，Point-LIO 和 DDDMR Docker 入口可设置与转发相同的 `ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=84`。离线回放使用录包保留的原始采样间隔。

原厂点云到机体坐标的有效变换及两路 IMU 重力方向对比见 EXP-0022 的 imu-axis-check.json。继续确认雷达点云与其内部 IMU 的轴向。当前名义 L2 启动参数仍处于离线参考阶段。采样脚本 `experiments/EXP-0022/sample_imu_pair.sh` 支持只读记录机体和雷达 IMU，后续由用户操控出两个独立方向的姿态变化时使用。


## L2＋机体 IMU 接入 DDDMR 建图（EXP-0025）

实机建图入口为 `go2_l2_mapping.launch.py`，只启动点云适配、地面参考 TF 和作者的 LeGO-LOAM 建图进程。Point-LIO 提供 `/odom`；DDDMR 自身的优化输出改到 `/dddmr/aft_mapped_to_init`，避免污染机体里程计适配器。未启动规划器、恢复行为或运动控制桥。

`mapping_cloud.py` 使用真实逐点 `time` 与 Point-LIO 的机体轨迹做去畸变，在 odom 中累积 3 帧，再转换到当前扫描结束时的 `dddmr_lidar` 坐标。该 frame 原点与固件发布点云一致，轴平行 base_link；它不是累计世界地图，也不会再次套用物理 radar 的安装旋转。DDDMR 的内部原始帧拼接关闭；`laser.scan_period=0` 用于关闭按机械旋转角推算时间的旧模型，真实约 15.42 Hz 和逐点时间仍用于前端补偿。

当前实验室候选参数见 `config/l2_mapping_lab.yaml`，由 `prepare_l2_mapping.py` 从原 Go2 配置独立生成，仿真配置不修改：

| 项目 | 首轮值 | 含义 |
|---|---:|---|
| 投影网格 | 96×360 | 重投影的虚拟角度栅格，不是 L2 有 96 条线 |
| 垂直角域 | −90°～90° | 对转换后的点计算球面投影 |
| 运动补偿累积 | 3 帧 | 使用 LIO 轨迹补偿历史点 |
| 建图距离 | 0.1～20 m | 实验室首轮范围 |
| 地面候选角域 | −90°～约−1.72° | 相对适配后的雷达坐标，方位覆盖整圈 |
| 地面跨环补点最大间隔 | 0.3 m | 不沿用演示的 1 m，也不填补首环到机体的盲区 |
| 关键帧距离/角度 | 0.15 m / 0.15 rad | 适配短程低速采集 |
| 地面可视化体素 | 0.15 m | 仿真原值为 0.4 m |
| ground_z | −0.31686765 m | 本次初始25帧测得的地面相对base_link高度，不是固定机身规格 |
| 回环 | 关闭 | 首轮只验证建图接口、资产保存与重载，后续另验回环 |

Cuboid 仍保留 EDU 的 1.1 倍包络 0.770×0.341×0.440 m；它不是解决地面缺失的参数，建图阶段未运行相应规划器。

### 从真实录包复现

在项目根目录运行，输出目录必须为空或不存在：

```bash
bash shared/dddmr/real/run_mapping_replay.sh \
  experiments/EXP-0024/motion-trial-02 \
  shared/dddmr/real/config/l2_mapping_lab.yaml \
  -0.3168676504844956 \
  .work/dddmr-real/replay-new
```

同一无网络 Docker 内完成原始录包回放、Point-LIO、DDDMR 和保存服务调用，不会重放任何控制话题。输出含 `summary.json`、参数/标定快照、各进程日志和 `maps/<时间目录>/`。地图包含 `map.pcd`、`ground.pcd`、`poses.pcd`、`edges.pcd` 和每帧 feature/surface/ground PCD，不能只拷贝单个 map.pcd。

共享入口的实际验证结果在 `experiments/EXP-0025/replay-final/`：24个关键帧、76个PCD资产，未缺文件。作者地图服务器已重载并提供首末关键帧。重载成功不等于MCL重定位或导航闭环通过。

### WiFi 实时建图

先按前文启动只读转发与 `GO2_IMU_SOURCE=chassis` 的 Point-LIO，保持站稳直到出现连续里程计。第三个终端启动：

```bash
ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 \
  bash shared/dddmr/real/run_mapping.sh wifi \
  "$PWD/shared/dddmr/real/config/l2_mapping_lab.yaml" \
  /go2/relay/cloud -0.3168676504844956
```

用户操控机器人扫描。地图保存服务为 `/save_mapped_point_cloud`；同一 ROS 域中 `ros2 service call /save_mapped_point_cloud std_srvs/srv/Empty '{}'` 可保存到 `.work/dddmr-real/maps/<时间>/`，不发送运动指令。站立高度或安装改变后应重新核对 ground_z 和标定，再重新生成配置。更换高度时 YAML 中 Cuboid 底面也要用同一 ground_z 更新：

```bash
/usr/bin/python3 shared/dddmr/real/prepare_l2_mapping.py \
  "$PWD/dddmr_navigation-main(1)/dddmr_navigation-main/src/dddmr_p2p_move_base/config/go2_mapping.yaml" \
  .work/dddmr-real/l2-mapping-new.yaml --ground-z=测得值
```

`GO2_MAPPING_PROFILE=raw` 仅保留先前未经L2点云适配的参考入口；当前实机使用默认l2模式。当前预览只来自短程往返，特征点图按作者设计较稀疏；需要更完整的环绕扫描来检查墙体、地面覆盖和回环，尚未启动自主导航。


PC 显示端可在加载 Humble 的终端执行：

```bash
source /opt/ros/humble/setup.bash
ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 rviz2 -d shared/dddmr/real/go2_mapping.rviz
```

该配置固定坐标为 map，分别显示 DDDMR 特征地图、累积地面、Point-LIO 当前扫描与关键帧。它用于上述实时建图节点运行期间；本轮已验证数据链路和地图重载，未另做GUI截图验收。


现场操控按用户要求改用PC键盘：另开交互终端运行 `./go2 keyboard wifi --robot`（或 `bash shared/run_wifi_keyboard.sh --robot`）。控制信号通过同一小电脑WiFi/SSH链路转高层DDS，建图仍在PC；原实验按键/速度保持。只读预检用`--check`。详见[当前WiFi键盘说明](../../go2_wifi_keyboard.md)。先空格停稳并Q退出键盘，再执行前述录包落盘和地图保存流程。


## WiFi 网卡松脱导致断流（EXP-0027）

2026-11-25 16:15:41 机载日志记录 USB 无线网卡移除、重新枚举，16:15:49 左右 PC 等待8秒超时，16:16:04 才恢复 WiFi。用户确认走动振动使接口松动。这不是雷达/IMU驱动失效的证据。用户已关闭 spin220 连接省电及当前 wlan0 省电，复查分别为 disable / off；不能据此将这次物理松脱归因于省电。

走动前固定网卡及接头，避免接头承受摆动拉力。断流后先由用户停止移动；保持 DDDMR 建图进程运行，在同一域保存已有地图：

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 PYTHONNOUSERSITE=1
ros2 service call /save_mapped_point_cloud std_srvs/srv/Empty '{}'
```

等待保存服务返回并核对地图文件后，再结束录包及估计/建图进程。修复连接后以新的输出目录重新开始采集、Point-LIO 和建图；不要只重启转发器并把缺失数秒 IMU 的片段接到原会话。旧地图和原始录包保留，后续需要续图时单独验证重定位/地图拼接。当前转发器没有可靠缓存重传或自动无损续接保证，8秒超时保护保留，错误信息增加断流处置提示。


## 有线采集与统一启动（EXP-0028）

Point-LIO 与 DDDMR 已通过数据和 TF 接入；`go2_live_mapping.launch.py` 进一步将前端、机体里程计/TF、运动补偿适配器、DDDMR建图一起启动。`run_live_mapping.sh` 在一个PC Docker内加载两个工作空间并运行该launch。仅建图，不包含控制节点或Gazebo。旧分开入口继续用于排查，不要和统一入口同时运行，以免重复发布TF和里程计。

传输可以用有线或WiFi，PC本地话题合同相同。当前有线先沿用机载eth10采集、SSH转发与统一校时；不直接将未校时的原厂消息送入前端。SSH到机载的IP换为192.168.123.18即可，现有`wifi`模式名实际表示host网络，不是算法对无线的依赖。

终端1（PC）：认证后启动有线只读转发（在工作区根目录执行，或直接用 `./go2 ssh wired` + `./go2 relay wired`）。

```bash
bash shared/connect_go2_ssh.sh wired
PYTHONNOUSERSITE=1 bash shared/dddmr/real/run_sensor_relay.sh \
  --host 192.168.123.18 \
  --socket .work/ssh-control/go2.sock --include-chassis-imu
```

终端2（PC）：启动完整估计/建图，新会话目录须为空或不存在（或直接用 `./go2 map`）。

```bash
bash shared/dddmr/real/run_live_mapping.sh \
  experiments/EXP-0028/live-wired-$(date +%Y%m%d-%H%M%S)
```

启动器显示地图目录；默认地面参考−0.3168676504844956m，可用第二个参数覆盖。改变站高需重新测量ground_z并同步Cuboid参数，不能只改变显示。

终端3（PC）：显示（或直接用 `./go2 rviz`）。

```bash
source /opt/ros/humble/setup.bash
ROS_DOMAIN_ID=84 ROS_LOCALHOST_ONLY=1 PYTHONNOUSERSITE=1 rviz2 \
  -d shared/dddmr/real/go2_mapping.rviz
```

仍由用户操控，站稳等前端初始化完成后再移动。录原始bag使用独立终端保留三路传感器，参照EXP-0026；该统一入口不自动录包、不自动保存地图。停止前在域84调用`/save_mapped_point_cloud`，确认保存后再Ctrl+C统一入口。不要启动另一套Point-LIO或DDDMR。离线回放入口也复用同一launch，进程合并日志为`stack.log`。
