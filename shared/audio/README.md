# Go2 文字流式对话

**部署目标已修正**：用户要求脱离电脑运行。当前机载服务与仅提交文字的命令见 [ONBOARD.md](ONBOARD.md)。本文 PC 端命令保留作调试，不能代表机载部署已完成。

当前目标：终端文字输入 → Kimi 流式正式回复 → 讯飞短句流式合成 → Go2 播放。无麦克风、ASR、动作工具或运动指令。默认多轮对话，保留最近 10 轮，`/reset` 清空，`/quit` 退出，Ctrl+C 停止并断开连接。对话历史只存在进程内存，不落盘。

## 配置与运行

复用 `.work/webrtc-venv`、`.work/xfyun.env` 和 `.work/xfyun_voices.json`，不重新训练音色。首次创建大模型配置：

```bash
./go2 chat --init-env
```

已有配置时此命令拒绝覆盖。编辑 `.work/dialogue.env`（被 Git 忽略，权限 600）：

```dotenv
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k3.1-pro
LLM_REASONING_EFFORT=low
LLM_API_KEY=填入自己的密钥
```

[Kimi 官方接口](https://platform.kimi.com/docs/api/overview)使用 Chat Completions。根据[思考参数说明](https://platform.kimi.com/docs/api/chat)，K3 始终思考，使用最低档 `reasoning_effort=low`，不要传 `thinking.type=disabled`。保留式思考内容只在内存中收集并随历史回传给 Kimi，不显示、不交给 TTS。低思考档不代表首字零等待，仍需实测。

```bash
# 先检查大模型文本与多轮上下文
./go2 chat --no-audio
# PC 扬声器实时 PCM 试听（需要 paplay）
./go2 chat --local-preview --voice mambo
# 已确认正常的 Go2 扬声器；IP 为原厂主板当前地址
./go2 chat --ip <GO2_IP> --voice mambo
# 单轮，完成播放后退出
./go2 chat --ip <GO2_IP> --text "请简单介绍一下自己。"
```

可用 `--volume 6` 设置机器人音量（不传则保留当前值）、`--voice man`/`teenager` 切换现有音色、`--history-turns` 调整保留轮数。公网复用 `--remote --sn <SN>`，账号密码在终端交互输入。错误时停止当前会话，避免把失败的回复写进历史；先检查配置与网络再重启。

## 流式方式与验证边界

默认 `--tts-mode sentences`：大模型 SSE 持续输出，按句末标点切段，保留逗号等句内语境，无句末标点最多 80 字切段；TTS 串行合成各段并立即输出 PCM。文本生成与合成独立并发，播放使用连续 WebRTC 音轨，PCM 按 20 ms 对齐，避免网络分片导致填零间隙。分段可能产生韵律停顿；极短、无标点回复可能等到回复结束才开始合成。此版本每轮播完再输入下一轮，尚无语音打断能力。

`--tts-mode duplex` 按[讯飞复刻协议](https://www.xfyun.cn/doc/spark/reproduction.html)在同一个 WebSocket 发送 status 0/1/2 文本帧并并发接收音频，仅会话首段做首字补偿。2026-11-27 真实服务测试：文本结束 2175 ms，首包音频 2565 ms，26 分片 / 3.50 秒音频，出现缓冲；因此未选为默认。对同样两句文本，默认短句路径首包 443 ms，文本结束 2003 ms，27 分片 / 4.16 秒音频，确认后半句送入前已得到前半句音频。测试文本后半句人为延迟 2 秒，不是大模型响应速度的测量。

`[timing]` 输出 `first_text_ms`（首个正式回复增量）、`first_audio_ms`（PC 收到首包 TTS PCM）、`llm_done_ms`（LLM 流结束）与 `done_ms`（本轮播放队列排空）。这些不等于测得的机器人声学起播时间。云端凭证不输出；仅完整成功的一轮加入历史。

已验证：本地模拟 LLM/TTS 的并发流式、UTF-8 分片、思考与正式回复隔离、低思考参数及历史保留、断线处理、两端错误取消、PCM 分片样本数。真实讯飞已测试；真实 Kimi API 与本入口的 Go2 对话尚未联调。基础 Go2 扬声器正常来自用户确认。

```bash
.work/webrtc-venv/bin/python -m unittest discover -s shared/audio/tests -v
```

测试只使用 127.0.0.1 临时端口与模拟服务，不连外网或机器人。受限沙箱可能需要允许本地监听。当前 Linux Project Infra 独立审查不可用。

## 2026-11-27 音质与入口更新

保留流式 PCM 播放，使用持久 PyAV 带限重采样器，音频网络分片不重置滤波器；输出连续拼成20ms帧，仅整轮尾帧补零。TTS 按完整句子合成，保留逗号上下文，仍可在后续句子生成时合成播放前句，最多80字切段。原 `./go2 speak`、`./go2 voice-train` 入口已移除，共享合成/播音代码保留。

相同预生成音频的对照中，用户评价 WebRTC 完整缓冲与分片两种方式都不错，megaphone 语速异常；该测试不能证明实时首响差异。调整后真实 Kimi 对话再次播放，用户确认“噪声完全消失”。连续重采样与句子切分一起调整，不能据此唯一归因，也不保证任意网络环境下无噪声。详见 EXP-0044。

2026-11-27 代码清理：独立训练/播报源码与包装脚本已删除（xfyun_clone_train.py、go2_audio_play.py、run_clone_train.sh、run_audio_play.sh），旧compare_audio_paths.py也已移除。当前共享音轨模块为shared/audio/webrtc_audio.py，xfyun_tts.py仅保留对话所需的配置/鉴权/流式合成核心，已删除训练音频处理、测试音和独立CLI。历史实验中的旧路径/命令仅描述当时的证据。部署器会清除机载上述退役文件及对应缓存，不动密钥、音色和实验产物。两端各13项测试通过，机载对话服务已恢复。
