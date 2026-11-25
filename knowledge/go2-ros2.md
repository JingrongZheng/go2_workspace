# Go2 的 ROS 2 通信

2026-11-17 查阅了宇树官方 `unitree_ros2` 仓库。用户指定的[宇树文档中心 ROS 2 页面](https://support.unitree.com/home/zh/developer/ROS2_service)未能取得正文，以下笔记基于[官方仓库中文 README](https://github.com/unitreerobotics/unitree_ros2/blob/master/README%20_zh.md)及[发布说明](https://github.com/unitreerobotics/unitree_ros2/releases)。

- SDK2 和官方 ROS 2 接入共用 DDS 通信机制。ROS 2 节点使用 Cyclone DDS 和宇树消息定义即可与兼容的 Go2 接口通信，省去 SDK 转发层。
- 仓库列出的测试组合为 Ubuntu 20.04 + Foxy 和 Ubuntu 22.04 + Humble，推荐后者。README 的 Foxy 流程单独编译 Cyclone DDS，Humble 可跳过这一步。复现实验应记录实际使用的版本和仓库提交。
- `cyclonedds_ws` 定义消息，`unitree_go` 包含 Go2 的状态等消息，`unitree_api` 包含 API 请求与响应消息。官方发布说明单独列出 Go2 状态管理接口的 Humble 支持及变更。
- 有线连接时，按 README 为直连网卡配置地址，并让 `CYCLONEDDS_URI` 使用实际网卡，`RMW_IMPLEMENTATION` 设为 `rmw_cyclonedds_cpp`。离线可以用 `setup_local.sh` 绑定回环接口 `lo`。
- 后续只读验证先用 `ros2 topic list` 看能否发现话题，再用 `ros2 topic echo /sportmodestate` 看能否收到状态样本。两步分别记录输出，便于区分发现和收包问题。

本轮仅查阅资料。指定页面的内容、各 SKU 和固件的适用范围，以及实际话题发现和收包仍待核对。
