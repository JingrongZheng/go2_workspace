# 仿真与实机接口约定草案

更新2026-11-23。下面是本项目拟议的ROS2内部接口，不是声称上游项目已有这些话题；实际话题用适配器/remap接入。没有可执行节点或实机启动入口。

| 数据 | 类型/内容 | 需要核实 |
|---|---|---|
| 原始雷达 | sensor_msgs/msg/PointCloud2 | xyz/intensity/ring/逐点时间；扫描方式、单位、时间起点及外参 |
| 雷达IMU | sensor_msgs/msg/Imu | 对应雷达、时间同步、轴向、角速度rad/s、加速度m/s²；不要直接把相机IMU当作已标定替代 |
| 深度/RGB | sensor_msgs/msg/Image + CameraInfo | 原始深度编码/比例、内参、时间及depth/color对齐；伪彩JPEG/MP4不能作为测距输入 |
| 估计位姿 | nav_msgs/msg/Odometry + TF | map→odom→base_link→传感器；不能由多个节点同时发布同一TF边 |
| 仿真真值 | 独立调试话题/文件 | 仅评价或明确标注的算法级实验使用，不混入传感器定位验收 |
| 全局路线 | nav_msgs/msg/Path等，具体适配待定 | frame、层高、方向、采样间距、路线可行性与更新事件；PCT输出不能直接视为速度 |
| 局部轨迹 | 由选定规划器定义 | SCAN的Bspline/时序轨迹需要对应跟踪器，不能仅改话题名变成Twist |
| 运动请求 | 内部速度或跟踪接口，待控制器确定 | Go2支持的自由度与模型输出一致，yaw/世界机体坐标区分，指令超时和唯一发送方 |

NeuPAN使用二维障碍点；若由3D雷达/相机生成，需独立地面/障碍处理并明确该分支的二维局限。不得对跨楼层路径直接删除z后当作同一平面路线。

仿真所有闭环节点统一使用仿真时钟并处理暂停/重置；实机禁用use_sim_time，记录采集端与服务器时差。服务器本地运行完整闭环，显示路径可独立切换远程画面/本地RViz。CPU/GPU/网络性能需要分别测量，不以视频帧率判断控制周期。

ROS版本边界：本项目PC基线Humble，上游PCT/SCAN主线/NeuPAN ROS wrapper多为Noetic。选择审查后的ROS2移植或明确隔离的ROS1实现；本准备不直接引入跨ROS桥接，也不将ROS1 launch命令写作ROS2启动命令。

## 已有地图定位的可替换边界（2026-11-23调研）

MCL是粒子滤波的位姿估计框架，NDT/ICP/GICP是点云配准方法，LIO是雷达惯性状态估计系统，它们不是互斥同层标签。常见候选：MCL-3DL；NDT地图匹配+滤波（hdl_localization使用UKF与NDT）；ICP/GICP地图匹配+连续里程计；FAST-LIO/Point-LIO提供连续里程计、另加已知地图匹配校正。small_gicp是配准库，不是带地图管理、丢失恢复和ROS节点的完整定位系统。

区分跟踪与全局初始化/重定位：给定粗初值连续跟踪并不保证在整栋楼自动识别楼层。FPFH+RANSAC/TEASER等全局候选可作重定位前端，hdl_global_localization也含二维BBS，后者不能直接当跨层解法。重复走廊/相似楼层、雷达观测稀疏和退化需要测试初值偏差、误楼层、遮挡、传感器丢帧及重定位成功率；没有一种算法天然解决全部问题。

拟议统一内部TF合同：连续里程计负责odom→base_link，已知地图定位负责map→odom，雷达匹配位姿先经外参/时刻转换；适配器统一语义，每条TF边仅单发布方。DDDMR地图服务器/感知规划仍需其地面与pose graph资产，换定位不能假设只改节点名。

调研来源：https://github.com/koide3/hdl_localization （作者ROS1主线UKF+NDT）、https://github.com/koide3/small_gicp （配准库）、https://github.com/HViktorTsoi/FAST_LIO_LOCALIZATION （社区FAST-LIO+低频地图匹配示例；旧ROS1/Python2.7/Open3D依赖，仅参考架构，不直接安装）、https://github.com/koide3/hdl_global_localization （BBS、FPFH_RANSAC、FPFH_TEASER）。均未验证本项目Humble/L1可运行。
