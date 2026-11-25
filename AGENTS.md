# Agent 入口

| 需要什么 | 去哪里 |
|---|---|
| 当前设计、目标和边界 | PROJECT.md |
| 长期结论及适用边界 | knowledge/index.md |
| 共享代码及运行入口 | TOOLKIT.md |
| 探索目标、验收条件和执行计划 | .project/plans/ |
| 具体尝试、验证命令和证据 | .project/experiments/ |
| 当前停点和继续条件 | 所属对象的 Continuation 小节 |
| 临时交接 | .work/<对象类型>/<ID>/HANDOFF.md |
| 外部资料 | library/index.toml |
| 审查协议及历史意见 | docs/reviewer-integration.md、.project/reviews/ |
| 本项目验证方式 | docs/verification.md |

接手时从 PROJECT.md 和相关对象开始，继续实验前先看所属 Plan 的执行计划。修改共享实现时同步 TOOLKIT.md，记录实际证据和下一步。项目专属约定可以追加在本文件。

通用工作流用 $project-infra Skill。CLI 位置见 .work/infra-runtime.md（由桌面应用打开项目时生成）；手动操作见 README.md。

## Go2 项目约定

本项目的开发、官方资料调研和实验复现始终使用 $project-infra 技能。接手时查看 `project-infra status`，再用 `project-infra context <ID>` 读取相关记录。用 Plan 管理目标和验收，用 Experiment 记录可独立验证的尝试、实际命令和结果。更新项目记录后运行 `project-infra validate`。
