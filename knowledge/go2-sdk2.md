# Go2 SDK2 应用开发

2026-11-17 查阅了宇树官方 SDK2 仓库。指定的[应用开发页面](https://support.unitree.com/home/zh/developer/Application_development)未返回可读正文，本笔记根据官方仓库整理。

## 官方入口

- C++ SDK 为 `unitree_sdk2`，采用 CMake，README 列出的预构建环境为 Ubuntu 20.04、GCC 9.4，支持 x86_64 和 aarch64。Go2 示例位于 `example/go2`，应用集成可参考 `example/cmake_sample`。[C++ SDK](https://github.com/unitreerobotics/unitree_sdk2) · [Go2 示例](https://github.com/unitreerobotics/unitree_sdk2/tree/main/example/go2)
- Python 接口为 `unitree_sdk2_python`，导入包名是 `unitree_sdk2py`。官方 README 要求 Python ≥ 3.8，依赖 Cyclone DDS 0.10.2。仓库的 `example/helloworld` 提供发布和订阅示例，可以在两个本地进程间检查 DDS 通信。[Python SDK](https://github.com/unitreerobotics/unitree_sdk2_python#dds-communication)

## 接口层次

- 高层接口调用机器人已有的运动服务，提供速度指令等能力。状态可从高层状态话题订阅，Python 入口为 `example/high_level/read_highstate.py`。做导航时，可以先考虑用 ROS 2 组织感知和规划，再通过设备接口读取状态、下发速度。
- 底层用 `LowState` 读取关节、IMU 等数据，用 `LowCmd` 表达关节命令。复现运动控制策略时，这一层通常更相关。若只验证收包，应选纯订阅示例。Python README 的底层状态和电机控制两节均指向 `lowlevel_control.py`，需查源码确认其行为。[Python SDK 的高低层说明](https://github.com/unitreerobotics/unitree_sdk2_python#high-level-status-and-control)
- SDK2 和 [ROS 2 接入](go2-ros2.md)都使用 DDS。SDK 提供客户端封装、发布订阅与请求响应接口。ROS 2 节点通过兼容的消息定义和 Cyclone DDS 可直接接入。
- 宇树的 `unitree_mujoco` 同时提供 C++ 和 Python SDK2 接入，主要面向底层控制验证。它发布 `SportModeState` 用于分析仿真状态，API 覆盖范围以仓库列出的消息为准。[官方 MuJoCo 接口说明](https://github.com/unitreerobotics/unitree_mujoco#supported-unitree-sdk2-messages)

本轮只查阅资料。实际可用接口取决于 Go2 型号和固件，SDK 安装和通信尚未验证。
