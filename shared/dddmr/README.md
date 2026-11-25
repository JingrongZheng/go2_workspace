# 本地 DDDMR 与 Go2 仿真

已在这台 Ubuntu22.04 / RTX3060Laptop / 16GB PC 上完成两个镜像、DDDMR全部25包、实际Gazebo/RViz显示、跨容器DDS及平地目标导航验证。证据见EXP-0015与`experiments/EXP-0015/`。

## 日常运行

在工作区根目录两个本地桌面终端分别启动：

```bash
bash shared/dddmr/run_local.sh simulation
```

```bash
bash shared/dddmr/run_local.sh navigation
```

两个组件启动后，在第三个终端为**当前配套Go2演示世界和地图**提供一次初始位姿：

```bash
bash shared/dddmr/run_local.sh initialize
```

这个初始化入口从Gazebo模型派生的`/odom`读取当前位置和朝向，向MCL的`/initial_3d_pose`发布一次小协方差初始估计，检查估计是否仍在附近。它只接受域83、localhost与演示位姿桥的里程计，**不是实机定位入口，也不是无真值定位评估**。导航默认粒子分布较宽，实测有一次重启后落入错误位置，不能省略初始化。也可使用RViz的`3D Pose Estimate`按实际地图位置和朝向手动提供初始位姿。

RViz状态正常后，用工具栏`3D Goal Pose`在可通行地面按住拖动，设置位置和朝向。先选起点附近的平地。原演示`xy_goal_tolerance=1.0m`，返回成功表示进入此容差范围，不保证停在厘米级目标点。

如果当前终端尚未取得docker组权限，将命令包在`sg docker -c '完整命令'`中即可。宿主机无需source ROS，ROS在各自容器内。

停止：各终端Ctrl+C，或：

```bash
docker stop go2-dddmr-navigation go2-dddmr-simulation
```

后台启动可在simulation/navigation命令前加`DDDMR_DETACH=1`；查看日志用`docker logs go2-dddmr-navigation`。重复执行启动命令时会检查现有容器：正在运行则复用，若Gazebo/RViz界面已关闭则仅恢复界面，不重启后台节点。仅恢复界面无需再次初始化。若同名容器已停止，脚本提示检查/保留旧容器，不自动删除。完整重启时才先停止两个组件，再按三步启动。

## 实现及环境

- 导航源码：用户完整解压目录`dddmr_navigation-main(1)/dddmr_navigation-main`，只读挂载；641文件的SHA256快照保存在实验目录，构建后复核未变化。
- 镜像`dddmr:go2-local`、`dddmr-sim:go2-local`；源码输出、地图和构建缓存在`.work/dddmr-local/`。
- Go2助手固定`b9e035230a5f7048bee7341de17ff4016d4ed8b8`，上游机器人源固定`fdac259518930c8f03e79189c4d0fdd00fc47483`。
- 上游导航Docker依赖：GTSAM4.2a9、PCL1.15.0、small_gicpv1.0.1、指定提交AprilTag；2并行编译，TRT关闭。
- Xwayland/X11使用专用Xauthority；NVIDIA GLX实测通过；RViz派生1280×850及标准停靠布局，不改原始源码或导航参数。
- ROS域83、localhost，两个容器使用host网络/ipc；Gazebo地址明确为127.0.0.1，解决本机默认地址路径下的transport启动崩溃。

## 重新构建

本机完整归档和依赖镜像已经缓存；首次编译耗时较长，普通启动无需重编。

```bash
bash shared/dddmr/build_navigation.sh
bash shared/dddmr/build_simulation.sh
```

`DDDMR_SOURCE`可指定完整导航源码目录。两个构建入口用`archive_cache.py`校验完整gzip/tar及版本；PCL使用官方发行`source.tar.gz`及发布SHA256校验。下载清单在实验`source-archives.json`。`*.partial`均为失败片段，不作为输入，不裁剪模型/测试数据/文档。

DockerHub不可达时，本机已从Docker官方AWS ECR的`docker/library/ubuntu:22.04`、`docker/library/ros:humble`获得基础镜像并设本地标签。容器Ubuntu/ROS软件源使用USTC；宿主机源不变。

## 验证与边界

```bash
docker exec go2-dddmr-navigation bash -c 'source /opt/ros/humble/setup.bash; python3 /project-tools/probe_runtime.py --duration 15'
```

探针只读订阅时钟、点云、里程计、TF、路径及速度，不发送控制。实际目标验证收到非空路径、非零速度、模型位移、末尾零速度及动作外层`SUCCEEDED`。动作结果自定义`status`字段默认0，不应误判为外层动作失败。

此基线使用作者已有地图、模拟多线雷达、CHAMP控制及Gazebo模型位姿派生里程计；初始化也使用模拟真值。CHAMP另发`/odom/raw`曾出现异常大数，原导航接的是正常`/odom`，不能声称腿式里程计通过。

L1适配、D435i原始RGB-D、同次采集双地图、高斯重建、无真值SLAM与楼梯通行尚未通过本次验收，继续按PLAN-0003及`docs/navigation/dual-map-data.md`推进。

## RViz常见图层

- `Map`：当前绑定`/map1/mapcloud`，由全部关键帧的角点特征合并、聚类过滤和降采样生成，不是全部墙面点云。平面特征另发`/map1/mapsurface`；`SubMap`合并附近关键帧的角点与平面点，所以可出现Map未显示的成片墙面，不能只用采样密度解释。当前演示无楼梯，world和地图需匹配。
- `SubMap`：`/sub_mapcloud`，从机器人附近关键帧合并并降采样得到的定位参考点云。当前选帧半径50m、默认分辨率0.1m，可能看起来覆盖很广、点数很多；不表示重新建图或实时雷达一帧。
- `ClearingTracing`：`/perception_3d_global/lidar/tracing_objects`，黄绿色线是历史障碍标记清除的射线调试显示，不是导航路径。取消勾选只隐藏线，不关闭清除功能，不会删除静态地图。Marker可能保留到后续覆盖/重置。
- `GlobalPath`等路径图层与上述清除射线含义不同。

当前洋红地面图dGraph的覆盖与/map1/mapground一致，并非Gazebo全部物理地面；实测43526点，XY外接范围约39×55m，内部覆盖不规则。未映射/未保留为地面的区域即使物理上可走，也不能默认可供当前图规划。范围核对见EXP-0015地面证据，不能仅凭现存资产断言作者手动删图。

当前map_Dgraph红色地块表示低距离/危险值，紫红表示较大值；A*跳过低于0.5m阈值的节点，边缘也可人为赋保守危险值，并非人工画的禁区。注意红色箭头属于P2P_Trajectories。局部感知用perception_local_current_observation（绿色障碍点）、Cuboid和候选/最佳轨迹观察；它们不是Nav2二维栅格costmap的同款显示。
