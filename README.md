# 项目工作台

本目录保存项目自己的设计与探索记录，Project Infra 程序安装在项目之外。
桌面入口会让你选择本目录并自动打开看板；Windows 便携版使用 ProjectInfra.exe，Ubuntu / Linux 自包含版使用 ProjectInfra。Agent 命令入口见 .work/infra-runtime.md，由应用启动时更新。无图形环境可直接使用下面的终端命令。
先让 Agent 阅读 AGENTS.md，结合你的实际目标填写 PROJECT.md，再按需要建立 Proposal、Plan 和 Experiment。
方向尚未决定开展时保留 Proposal；创建 Plan 即开始探索。空项目没有演示数据或预设实验。
Plan 的 Execution plan 保存随探索动态更新的整体 steps，并默认带未完成的“共享实现整理”步骤。执行 Agent 完成后勾选并写“结果：”及具体处理或无需抽取的原因；非放弃 Plan 未完成此项时，程序拒绝交付与结束。普通 Experiment 不重复设置此项。context EXP-编号 会带入所属 Plan 的当前执行计划。

在本目录运行（未激活安装环境时使用安装目录内 `project-infra.cmd` 或 `project-infra` 的完整路径）：

```sh
project-infra validate
project-infra serve --port 8765
```

在浏览器打开 http://127.0.0.1:8765/。端口被占用时换一个端口，不要终止未知服务。
从项目子目录运行会向上寻找最近的 .project/config.toml；也可显式指定 project-infra --root 项目目录 serve。
每个看板对应一个项目，多个项目使用不同端口。

创建记录示例（编号以命令实际输出为准，不要求预先有这些记录）：

```sh
project-infra new proposal --title "待考虑的方向"
project-infra new plan --title "开始探索一个问题"
project-infra new experiment --plan PLAN-0001 --title "一次具体尝试"
project-infra context PLAN-0001
```

PROJECT.md 保存正式采用的设计主干；TOOLKIT.md 索引本项目实际共享代码，不复制工具自身源码。
knowledge/ 保存跨实验可复用的结论与边界，并链接来源实验；shared/ 或已有源码包保存真实共享代码，experiments/ 只保留薄调用入口。两者都独立于某个 Experiment。
启动时先运行 reviewer status 并按 docs/reviewer-integration.md 完成当前环境能力自检。交付时运行 deliver <ID>；进程适配器会自动执行，宿主模式返回交接目录。未接入时明确记录未执行独立审查，不显示为通过。成功意见追加到 Review，原始各轮意见保存在 .project/reviews/；不会覆盖往期。程序不自带模型；交接前冻结项目写入，恢复原权限后才记录意见并继续工作。
验证入口见 docs/verification.md，质疑者指引见 docs/reviewer.md。
未完成工作的停点写在对象 Continuation 中；.work 只存临时现场。

重复 init 只补缺失文件，不覆盖现有项目文件。已有 AGENTS.md 会保留，需人工或 Agent 将必要导航合并进去。
更新安装包与初始化项目相互独立，不自动改写项目记录。
