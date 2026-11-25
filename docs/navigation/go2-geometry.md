# Go2 EDU 名义安装几何

2026-11-24，EXP-0019。仅静态资料核查，硬件测试继续延后；不是已验证的实机启动配置。

## 来源和约定

使用[宇树官方Go2 URDF](https://github.com/unitreerobotics/unitree_ros/blob/master/robots/go2_description/urdf/go2_description.urdf)，不是根据渲染图比例估算。保存的原文为 experiments/EXP-0019/go2_description.urdf，SHA256及数值见 shared/dddmr/real/go2_nominal_geometry.json。当前保存master快照，未解析commit，后续不随远程分支自动变化。

官方根坐标系名为 `base`；以下变换表示子坐标系在父坐标系中的位姿，即 `p_parent = R * p_child + t`。长度单位米，RPY单位弧度。应用中的base_link只有与此base完全重合时才能直接使用这些数值。URDF惯性原点是质心，不能当作base坐标原点另行叠加。

| 父→子 | 平移 xyz / m | RPY / rad |
|---|---|---|
| base→radar | 0.28945, 0, -0.046825 | 0, 2.8782, 0 |
| base→imu | -0.02557, 0, 0.04232 | 0, 0, 0 |
| imu→radar（推导） | 0.31502, 0, -0.089145 | 0, 2.8782, 0 |
| base→front_camera | 0.32715, -0.00003, 0.04297 | 0, 0, 0 |

radar的俯仰角为164.9087126°，xyzw四元数为[0, 0.9913405653290647, 0, 0.1313159683094573]。不能随手改为零。front_camera是原厂模型前相机，不是外接D435i。

## 与Point-LIO的接口

URDF的imu与雷达内置IMU不是可直接等同的坐标系。上表提供机体安装名义关系；Point-LIO的LiDAR–IMU配置取决于实际使用哪一个IMU，以及点云是否已转换到机体/里程计坐标。

[L2 SDK2官方坐标定义](https://github.com/unitreerobotics/unilidar_sdk2#2-coordinate-system-definition)给出内置IMU原点在雷达坐标系中为[-0.007698,-0.014655,0.00667]m，轴向平行。[宇树Point-LIO L2配置](https://github.com/unitreerobotics/point_lio_unilidar/blob/main/config/unilidar_l2.yaml)的extrinsic_T为相反符号[0.007698,0.014655,-0.00667]，extrinsic_R为单位阵。须按被采用实现的坐标变换公式核对，不能仅凭注释中的“from/to”判断方向，更不能把base→radar直接填进去。

用户已确认Go2 EDU，内置雷达可能为L2，尚未确认。这份通用Go2模型没有证明当前EDU的具体雷达型号或安装修订。后续只读测试核对型号、原始数据frame_id和是否已有坐标变换，再把名义值启用到实机TF；避免重复旋转点云。硬件测试未恢复前不进行连接或采集。

## EDU包络与Cuboid

用户提供规格：站立长宽高0.70×0.31×0.40m，关机趴下0.76×0.31×0.20m。可作为初始包络尺寸参考，不需要按图片猜尺寸。

这些总尺寸没有给出包络中心相对base的位置，也没有包含明确的步态扫掠范围、机载设备和安全裕量。不能直接把z=0..0.40写进机体坐标，亦不能无依据假定前后对称。实机Cuboid最终需结合站姿/运动和base离地关系确定中心、范围及裕量。官方URDF的base碰撞盒0.3762×0.0935×0.114m只代表简化躯干，不是整机导航包络；不沿用仿真Cuboid。

## 继续条件

先以本文件作为实机参数依据，保持独立于shared/dddmr/run_local.sh仿真入口。硬件恢复测试后，核对原始点云及配套IMU坐标、静止重力方向、地面平面与安装关系，再启用TF并验证Point-LIO。实际运动前完成Cuboid中心及运动余量核查。

## 官方 Point-LIO 参数与 Go2 整机话题

宇树 [SDK2 中文坐标系定义](https://github.com/unitreerobotics/unilidar_sdk2/blob/main/README_CN.md#2-坐标系定义) 的平移是 IMU 原点在雷达坐标中的位置。宇树 Point-LIO 的 [L1](https://github.com/unitreerobotics/point_lio_unilidar/blob/main/config/unilidar_l1.yaml) 和 [L2](https://github.com/unitreerobotics/point_lio_unilidar/blob/main/config/unilidar_l2.yaml) YAML 均以 SDK 的 /unilidar/cloud 和 /unilidar/imu 为输入，extrinsic_R 为单位阵，extrinsic_T 为 [0.007698, 0.014655, -0.00667] m。[上游计算](https://github.com/unitreerobotics/point_lio_unilidar/blob/main/src/laserMapping.cpp#L136-L155) 使用 p_imu = R*p_cloud + t，方向按源码公式解释。两个型号默认值相同，所以数值无法用于判定硬件型号。

实机使用 Go2 整机固件的 /utlidar/cloud 与 /utlidar/imu。EXP-0018 的同点配对测得该云到原厂 /utlidar/cloud_base 的有效变换，EXP-0022 的双 IMU 对照表明这个变换和单位雷达–IMU旋转不能直接合用。静态单一重力方向不足以唯一确定旋转。保留官方偏移作为独立 SDK 坐标下的参考，实机 lever arm 仍需核对原点定义。

用户操控时可用 EXP-0022 的 sample_imu_pair.sh 只读记录，再由 fit_imu_rotation.py 用两路陀螺的多轴变化拟合旋转。解算结果以机体 IMU 为目标坐标，需继续核对与 base_link 的轴向和原点，检查留出样本误差及 Point-LIO 回放。陀螺数据只够估计旋转，平移要结合硬件原点和对应坐标系另行确认。
