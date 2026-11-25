# DDDMR技术栈核查

原调研2026-11-23；2026-11-24本机Docker已完成原栈Go2平地导航验证（EXP-0015），不是服务器/实机/楼梯验收。手动导航源码用文件SHA256快照标识，无Git元数据；Go2源与依赖已固定。

| 层 | 实现 | 边界 |
|---|---|---|
| 运行环境 | ROS2 Humble、colcon、Docker；x86_64与Jetson l4t路径 | 本机镜像/25包/窗口/平地目标通过；服务器未验 |
| 建图 | dddmr_lego_loam，改造LeGO-LOAM-BOR；条件回环、pose graph编辑/合并 | 不是FAST-LIO；默认定位地图含自有pose graph，不是任意PCD即可等价替换 |
| 定位 | dddmr_mcl_3dl，改造mcl_3dl粒子滤波，子地图、点云特征与里程计 | 消费上述pose graph，需初始位姿；不是仅靠轮式里程计 |
| 感知 | dddmr_perception_3d；静态/动态图层，障碍标记清除、禁入/限速层 | 模块声明支持L1/深度相机，不代表整套建图默认参数适配L1 |
| 全局规划 | graph-based A*；可行走地面静态图与传感器动态图 | 不是PCT；三维场景地面图不是四足足端落脚规划 |
| 局部规划 | dddmr_local_planner，受DWB启发的生成器/critic插件、3D cuboid碰撞检查 | 不是SCAN/NeuPAN；源码支持扩展不等于默认启用所有策略 |
| Go2局部配置 | differential_drive_simple/rotate插件，采样vx和wz，collision/stick_path/pure_pursuit等评分 | 机体运动近似不是将四足物理模型改成轮式，也没有足端接触优化 |
| 调度 | dddmr_p2p_move_base有限状态机 | 协调目标、规划、执行、恢复 |
| Go2仿真 | dfl_mobilerobot_simulator的go2分支，来自unitree-go2-ros2 Humble；Gazebo Classic、Go2 URDF、CHAMP | 不等于Unitree实机内部控制器，也不是已验证爬楼RL策略 |
| 显示 | RViz2＋Gazebo界面 | 可移到服务器远程显示，原教程同宿主两个容器 |

默认Go2定位导航示例加载既有gz_go2_demo_world地图，go2_localization.launch启动mcl_feature、地图server、mcl_3dl、global_planner、p2p_move_base和RViz。仿真脚本禁用CHAMP两个EKF，并提供gz_pose_to_ros2.py，将Gazebo模型位姿转换成/odom及TF。故默认演示含真值衍生里程计；不能把它视为独立传感器SLAM/里程计验收。后续要新增不依赖真值的传感器估计测试。

对本项目：DDDMR可以作为完整导航基线候选；先保留其原算法跑通，再考虑替换建图/全局/局部模块。替换Point-LIO、PCT或NeuPAN不是改一个插件名即可完成；特别mcl_3dl依赖pose graph格式。楼梯落脚、支撑及运动可执行性仍须控制层验证。

来源：
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_lego_loam
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_mcl_3dl
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_perception_3d
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_global_planner
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_local_planner
- https://github.com/dfl-rlab/dddmr_navigation/tree/main/src/dddmr_p2p_move_base
- https://github.com/dfl-rlab/dddmr_navigation/blob/main/src/dddmr_p2p_move_base/config/go2_localization.yaml
- https://github.com/dfl-rlab/dfl_mobilerobot_simulator/tree/go2
- https://github.com/dfl-rlab/dfl_mobilerobot_simulator/blob/go2/scripts/apply_go2_changes.bash
- https://github.com/dfl-rlab/dfl_mobilerobot_simulator/blob/go2/extra_files/robots/configs/go2_config/scripts/gz_pose_to_ros2.py

本地操作顺序为simulation、navigation、initialize，见shared/dddmr/README.md。MCL必须提供初始位姿；默认大粒子分布曾在重启后定位到错误区域。演示initialize仅从Gazebo模型位姿播种一次，不用于实机或无真值评测。

2026-11-24补充：作者Go2演示的Gazebo真值/odom不等于LeGO-LOAM算法依赖真值或必须使用IMU。本地featureAssociation.cpp提供laser_odometry（激光计算相对运动）和外部odom分支；Go2默认配置选wheel_odometry。当前定位导航launch只启动mcl_feature，不是完整在线建图。移除真值可评估已有纯激光分支，不以添加IMU/替换为LIO为强制前提；odom发布与TF仍需完整接线验证。

Go2仿真IMU已实查（2026-11-24）：当前模型内有100Hz的Gazebo IMU插件，/imu/data实际发布sensor_msgs/Imu，见EXP-0015/imu-runtime-probe.json。传感器存在/发布与算法是否订阅融合必须分开；当前真值/odom桥没有改为IMU估计。

2026-11-24 FAST-LIO2比较：相对本地LeGO-LOAM纯激光前端的角点/平面点提取、帧间特征关联与迭代最小二乘，FAST-LIO2以IMU传播状态、紧耦合迭代误差状态滤波进行雷达更新，支持不提取人工特征的原始点scan-to-map，并用ikd-Tree维护增量地图。点云匹配仍有局部几何约束；不是“无约束直接求位姿”。输入同步、逐点时间、IMU轴向/外参与噪声需要核验。DDDMR版本附有条件回环、位姿图编辑及MCL格式，FAST-LIO2的LIO/增量地图不直接等价替换这些产物和后端。对Go2快转/抖动的潜在收益是方法层面判断，L1实测精度、稳定性和负载尚未验证，不能按论文通用性能直接承诺。官方FAST_LIO主仓库说明为ROS1/catkin，当前Humble需另选并锁定ROS2移植版本。来源：https://arxiv.org/abs/2107.06829 、 https://github.com/hku-mars/FAST_LIO ；已读本地featureAssociation与LeGO README。本次未变更运行实现。

2026-11-24 Map/SubMap重要更正：此前仅用降采样说明额外墙面不完整。实查dddmr_pg_map_server.cpp，mapcloud只由cornerCloudKeyFrames_合并而来，执行0.2m聚类并移除<10点簇，再按配置降采样；surfCloudKeyFrames_单独合并发布mapsurface。SubMaps同时合并角点和平面点，故整片平面墙可只在SubMap显示。地图server从poses.pcd及pcd/*_feature/_surface/_ground读取，不直接读取根目录map.pcd；SubMap通过同一server获取关键帧。该代码路径足以解释图中区别，不能据此断言作者手工编辑删墙或坐标错位，资产是否有历史编辑仍未知。只读话题证据map-layer-counts.json，不更改运行地图。
