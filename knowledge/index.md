# 项目知识

在此链接经过提炼、值得跨实验复用的知识文档。每份知识写清结论、适用边界及来源实验/证据，按需提供重跑入口；有价值的负面结论同样可以沉淀。
不保存全部实验流水账，不另设历史层或知识状态机。当前采用的设计仍由 PROJECT.md 维护，外部论文和手册放 library/。

- [Go2 的 ROS 2 通信](go2-ros2.md)

- [Go2 的 SDK2 应用开发](go2-sdk2.md)

- [L2 点云＋机体 IMU 的实测输入基线](go2-l2-chassis-imu-baseline.md)：当前估计输入、WiFi 实测频率、时间戳与适用边界，来源 EXP-0024。

- [DDDMR `lego_loam_bor` 在线回环并发段错误](dddmr-loop-closure-race-bug.md)：`mapOptimization.cpp` 跨回调组无锁并发读写 `isam`/`gtSAMgraph`/位姿容器的源码证据与规避方式，来源 EXP-0033。
