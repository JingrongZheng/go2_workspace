# L2 点云与机体 IMU 的实测输入基线

记录日期：2026-11-25。来源实验：EXP-0024，第二次用户手动走动录包 `motion-trial-02`。

当前 Point-LIO 使用 **L2 点云＋完整机体 IMU**。L2 内置 IMU 仍采集并录包，供对照检查，不参与当前位姿估计；这不表示关闭雷达内置 IMU 硬件。

| 数据 | PC 话题 | 实测接收频率 | 本次消息数 | 当前用途 |
|---|---|---:|---:|---|
| L2 点云 | `/go2/relay/cloud` | **15.42 Hz** | 1247 | Point-LIO 输入 |
| 机体 IMU | `/go2/relay/chassis_imu` | **385.14 Hz** | 30986 | Point-LIO 输入 |
| L2 内置 IMU | `/go2/relay/imu` | **240.10 Hz** | 19415 | 仅录制对照 |

## 条件和适用边界

- 链路：机载电脑通过内部 eth10 订阅 Go2，经过局域网 WiFi SSH 转发，PC 本地 ROS 2 接收；使用 `run_sensor_relay.sh --include-chassis-imu`。
- 录包时长约 80.86 秒。频率来自转发器对每路首末接收时刻计算的 `(消息数−1)/(末接收时刻−首接收时刻)`，各路统计区间略有差别。
- 数值是本次端到端实测接收频率，**不是硬件标称采样率，也不是未来运行的固定频率**。网络、调度和采集负载改变后需重新测量，不应将这些数值直接当作固定积分步长。
- 机体 IMU 时间间隔使用 LowState 原生毫秒 tick，时间原点由软件估计；不是与 L2 硬件同步。算法应使用各条消息的实际时间戳。
- 当前选择通过静止和两轮短程走动检查；不等同长期定位、自主导航或楼梯验收。

## 证据和入口

- [原始频率日志](../experiments/EXP-0024/motion-02-relay.log)：末三条 JSON 包含每路 samples 与 hz。
- [独立录包元数据](../experiments/EXP-0024/motion-trial-02/metadata.yaml)：时长和消息计数。
- [完整实验记录](../.project/experiments/EXP-0024.md)。
- [共享运行说明](../shared/dddmr/real/README.md)：选择 `GO2_IMU_SOURCE=chassis`，显式输入机体 IMU 话题。
