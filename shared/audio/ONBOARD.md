# 机载独立对话

“脱机”在本项目指脱离 PC，机器狗仍可上网。当前架构：PC 仅提交文字 → 机载电脑维护对话并调用 Kimi → 机载电脑调用讯飞合成 → 内部 WebRTC 发送到原厂主板扬声器。机器狗端始终需要能够访问两个云 API；PC 无需承担云调用、合成或音频转发。麦克风、ASR 后续再接入。

## 机器与进程

本次目标机载电脑为 unitree@192.168.123.18，ARM64、Python 3.8.10。代码目录 `/home/unitree/go2-dialogue`，独立 Python 在 `.venv`，用户配置在 `.work/dialogue.env`、`.work/xfyun.env`、`.work/xfyun_voices.json`，这些文件权限 600，不输出密钥。原厂主板扬声器内部地址默认 192.168.123.161，与机载电脑 .18 区分；无需通过 PC 传音频。实际播音仍需机载路径实测。

服务仅监听机载回环 127.0.0.1:8765，PC 使用现有 SSH 认证访问，不暴露无认证的局域网 HTTP 端口。`/ask` 返回任务 ID 后由服务独立执行，PC 断开不会取消已接受的任务；回复可从 `/jobs/<ID>` 查询。仅一条对话正在运行，忙碌时拒绝新请求，完成后保留最近 10 轮上下文；最多保留最近 32 条任务状态。服务重启后上下文和任务状态清空。

## 部署与启动

先在 PC 下载匹配 Python 3.8 / ARM64 的 wheels 到 `.work/onboard-dialogue/wheels`，requirements 为 `shared/audio/requirements-onboard.txt`，另加 `pip==25.0.1` 引导轮子。通过 `deploy_onboard_dialogue.py` 一次性传入源码、已用 WebRTC 2.2.0 驱动、离线依赖、ARM64 PortAudio 库；配置仅在目标不存在时通过 SSH 写入，避免覆盖机载配置。无需 apt/sudo，不改导航环境。机载 `install_onboard_runtime.sh` 使用 `venv --without-pip` 加本地 pip wheel 引导，适应 Ubuntu 缺 ensurepip 的环境。

PC：

```bash
cd /home/suiliang/go2_workspace
python3 shared/audio/deploy_onboard_dialogue.py
```

机载启动（可在 SSH 终端运行一次）：

```bash
bash /home/unitree/go2-dialogue/shared/audio/manage_onboard_dialogue.sh start
```

此后进程由机载 systemd 用户服务管理，不附属于 PC 提交程序。查状态或停止，把 `start` 改成 `status` / `stop`。用户服务开机启动依赖用户会话；本机 `Linger=no`，目前不宣称无人登录时开机自启。如后续要求开机即运行，再配置并实际重启验证。

PC 提问（复用已有 SSH 控制套接字）：

```bash
cd /home/suiliang/go2_workspace
./go2 ask --health
./go2 ask "你好，请简单介绍自己。"
# 只发送，提交后立即断开；机器人继续处理
./go2 ask --submit-only "请说一句欢迎词。"
./go2 ask --reset
```

机载 Wi-Fi 恢复后可以用 `--host <机载电脑Wi-Fi地址>`，注意是机载电脑的 SSH 地址。新 SSH 连接可先用项目 `shared/connect_go2_ssh.sh --host ...` 建立，再用 `--socket` 指向对应套接字。

`--health` 只报告进程与配置状态，不进行云 API 连通性检查。`config_ready=true` 只表示本机配置字段齐全，云端真实请求通过才可证明调用可用。当前用户要求忽略 Wi-Fi 故障，不能把代码已部署或 health 正常当作真实云端对话成功。

## 当前边界

音色默认 mambo，模型 kimi-k3.1-pro、reasoning_effort=low，正式回复分段合成并流式播放；思考字段仅留内存并按协议回传。程序全程没有运动 API。默认不记录对话或密钥，只向任务提交者返回正式回复与耗时。当前先做文本对话，每轮播放完成后再接下一次请求；没有 ASR 或中途打断。

## 2026-11-27 当前实测

代码和独立 ARM64 运行环境已安装完成，aiohttp 3.10.11 / PyAV 12.3.0 / aiortc 1.9.0 / sounddevice / WebRTC 驱动导入通过。`go2-dialogue.service` 在机载 systemd 中 active/running；PC 执行 `./go2 ask --health` 返回 `runs_on=robot_computer`、`config_ready=false`、`config_problem=missing_llm_key`、`audio_enabled=true`、`cloud_connectivity_verified=false`。这证明机载服务及 SSH 提交路径已可用，不证明真实对话或播放通过。密钥应填机载 `/home/unitree/go2-dialogue/.work/dialogue.env`，而不是只填 PC 配置；以后部署保留已有机载配置，不覆盖它。

## 2026-11-27 17:55 真实链路通过

用户恢复机载 Wi-Fi 并提供本机 `api_key.txt`，经 SSH stdin 用 `configure_onboard_key.py` 写入机载 `.work/dialogue.env`，权限 600，未输出密钥。账号 `/models` 不含原计划的 highspeed 型号，用户选择实际可用的 `kimi-k3.1-pro`，思考强度 low。

PC `./go2 ask` 已完成真实机载 Kimi → 讯飞 → WebRTC 播放，用户确认听到“你好，我是机器狗。现在开始测试流式对话。”且声音正常。该短回复 first_text_ms=2448、llm_done_ms=2540、first_audio_ms=2926、done_ms=7540；由于文字回复很短，首包音频晚于文字生成结束，本次不能据此证明实际发生了“LLM 未结束就出音频”。程序采用短句流水线，生成足够长时可以重叠处理；端到端每次的耗时仍以实际输出为准。

当前可直接运行 `./go2 ask "你的问题"`。密钥已在机载，电脑无需保存 Key。首次 WebRTC 曾出现 NoSdpAnswerError，重试握手成功后完成实机播放；未改网络或固件，也没有证据声称其根因已经修复。

## 无线提交的 SSH 会话选择

`./go2 ask --host 192.168.110.87 "问题"` 自动复用 `.work/ssh-control/go2-wifi.sock`，有线默认地址复用 `go2.sock`，显式 `--socket` 优先。先前入口固定使用有线 socket，导致无线已登录仍报 Permission denied，已修复。当前实测无线 SSH 两端为 PC `192.168.110.120` → 机载 `192.168.110.87:22`，同一路径健康查询通过。

若改用其他 Wi-Fi 地址，可设置环境变量 `GO2_WIFI_HOST`，或显式传 `--socket`。未知地址不会擅自复用其他主机的控制套接字，因为 OpenSSH 实际通过 socket 对应的连接执行命令，目标字符串不同也不能保证改变路径。

## 2026-11-27 音质与入口更新

保留流式 PCM 播放，使用持久 PyAV 带限重采样器，音频网络分片不重置滤波器；输出连续拼成20ms帧，仅整轮尾帧补零。TTS 按完整句子合成，保留逗号上下文，仍可在后续句子生成时合成播放前句，最多80字切段。原 `./go2 speak`、`./go2 voice-train` 入口已移除，共享合成/播音代码保留。

相同预生成音频的对照中，用户评价 WebRTC 完整缓冲与分片两种方式都不错，megaphone 语速异常；该测试不能证明实时首响差异。调整后真实 Kimi 对话再次播放，用户确认“噪声完全消失”。连续重采样与句子切分一起调整，不能据此唯一归因，也不保证任意网络环境下无噪声。详见 EXP-0044。

2026-11-27 代码清理：独立训练/播报源码与包装脚本已删除（xfyun_clone_train.py、go2_audio_play.py、run_clone_train.sh、run_audio_play.sh），旧compare_audio_paths.py也已移除。当前共享音轨模块为shared/audio/webrtc_audio.py，xfyun_tts.py仅保留对话所需的配置/鉴权/流式合成核心，已删除训练音频处理、测试音和独立CLI。历史实验中的旧路径/命令仅描述当时的证据。部署器会清除机载上述退役文件及对应缓存，不动密钥、音色和实验产物。两端各13项测试通过，机载对话服务已恢复。
