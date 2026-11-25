# DDDMR `lego_loam_bor` 在线回环并发段错误（上游 Bug 记录）

## 结论与适用边界

- **现象**：在 `dddmr_navigation` 的在线建图节点 `lego_loam_node`（`lego_loam_bor`）中开启 `mapping.enable_loop_closure: true` 且连续高频触发回环边插入时，进程发生段错误退出（`SIGSEGV`，`exit code -11`）。
- **根因**：确认是上游源码的**多线程数据竞争（Data Race）**，而非 L2 点云或配置错误。
- **适用边界**：影响使用 `rclcpp::executors::MultiThreadedExecutor` 的在线节点 `lego_loam_node`；离线单线程/同步优化不受影响。
- **来源实验**：[EXP-0033](../.project/experiments/EXP-0033.md)，复现日志 `experiments/EXP-0033/replay-201833-loop/stack.log`。

## 源码证据（`dddmr_navigation`）

1. **多线程执行器 + 独立回调组**：
   - `src/dddmr_lego_loam/lego_loam_bor/src/lego_loam_node.cpp` L31：使用 `rclcpp::executors::MultiThreadedExecutor`。
   - `src/dddmr_lego_loam/lego_loam_bor/src/mapOptimization.cpp` L163–172：
     - `timer_run_`（1 ms，调用 `MapOptimization::run()`）绑定在 `timer_run_cb_group_`；
     - `timer_loop_closure_`（1000 ms，调用 `MapOptimization::loopClosureThread()`）绑定在独立的 `timer_loop_closure_cb_group_`。
2. **声明了互斥锁但全程未加锁**：
   - `src/dddmr_lego_loam/lego_loam_bor/include/mapOptimization.h` L309 声明了 `std::mutex mtx;`；
   - `mapOptimization.cpp` 全文没有任何 `std::lock_guard` / `std::unique_lock` / `mtx.lock()` 调用。
3. **无保护并发读写的共享成员**：
   - `gtSAMgraph` 与 `isam`：`addEdgeFromPose()`（L1225–1231，由 `loopClosureThread` 调用）与 `saveKeyFramesAndFactor()`（L1917–1972，由 `run()` 调用）并发执行 `gtSAMgraph.add(...)`、`isam->update(...)` 和 `gtSAMgraph.resize(0)`；
   - `pose_graph_`（`std::set`）：L1213 与 L2045 并发 `insert`；
   - `cloudKeyPoses3D` / `cloudKeyPoses6D`：`performLoopClosure()` 遍历读取的同时，`saveKeyFramesAndFactor()` 并发 `push_back` 可能触发 `std::vector` 扩容重分配；
   - `aLoopIsClosed`：非原子 `bool`，L1232 写入，L2077/L2101 读取并清除。

## 复现证据摘要

- 输入：真实 Go2 EDU 392.4 秒闭环录包（`.work/sessions/bag-20261125-201833`），`enable_loop_closure: true`、`history_keyframe_search_num: 30`、`surrounding_keyframe_search_num: 50`。
- 日志在 1 Hz 连续插入多条低误差回环边（`254→147` ICP `0.04`、`255→148` ICP `0.03`、`256→149` ICP `0.01`、`257→150` ICP `0.10`、`258→150` ICP `0.02`）后立刻触发 `exit code -11`。

## 建议给上游的 Issue / 修复方向

- 在 `MapOptimization` 中用已声明的 `mtx` 保护 `gtSAMgraph`、`isam`、`pose_graph_`、`cloudKeyPoses3D/6D` 和 `aLoopIsClosed` 的临界区（或将 `timer_loop_closure_` 放入与 `timer_run_` 相同的 `MutuallyExclusive` 回调组，避免并发修改 iSAM2 与位姿容器）。
- 本项目在保持上游只读期间，现场默认保持 `enable_loop_closure: false`，改用离线同步位姿图优化（`shared/dddmr/real/optimize_pose_graph.py`）对已保存地图执行回环闭合。
