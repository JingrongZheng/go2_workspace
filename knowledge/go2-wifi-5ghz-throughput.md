# Go2 无线传感器转发需使用 5 GHz WiFi

- **结论**：Go2 拓展坞经 USB Realtek 网卡（`88x2cu`，`wlan0`）运行 `./go2 relay wifi`（同时转发 L2 点云 15 Hz + L2 IMU + 机体 IMU 500 Hz，需 4–6 Mbps 稳定带宽）必须连接 **5 GHz WiFi**；在实验室 2.4 GHz 环境下实际吞吐可跌至不足 1 Mbps，导致传感器流排队超时（`Not enough IMU samples` 或 `Corrected sensor timestamp outside the live window`）。
- **实测对照（2026-11-26，来源 `EXP-0037`，机载 `192.168.110.87`）**：
  - 2.4 GHz `spin220`（2462 MHz，信道 11，20 MHz，802.11bgn）：SSH `dd` 实测吞吐 **`0.5 Mbps`**（2.10 MB / 31.758 s）→ `./go2 relay wifi` 无法启动。
  - 5 GHz `spin220_5G`（5.3 GHz，信道 60，802.11AC 867 Mb/s）：SSH `dd` 实测吞吐 **`97.2 Mbps`**（4.19 MB / 0.345 s，提升约 **194 倍**）→ 满足实时转发。
- **配置要点**：
  - 机载默认监管域为 `country 00`，5 GHz 高信道处于被动扫描状态，需设置 `CN` 国家码（`/etc/modprobe.d/cfg80211-regdom.conf` 写入 `options cfg80211 ieee80211_regdom=CN`）。
  - `go2-usb-wifi-bind@.service` 仅负责绑定 `88x2cu` 驱动，自动重连由 NetworkManager 决定，应为 5 GHz 连接设置高优先级（如 `autoconnect-priority 100`）并关闭同名 2.4 GHz 的 `autoconnect`。
- **复测命令**：
  ```bash
  python3 -c 'import subprocess,time; t0=time.monotonic(); b=subprocess.check_output(["ssh","-T","-S",".work/ssh-control/go2-wifi.sock","-o","BatchMode=yes","unitree@192.168.110.87","dd if=/dev/zero bs=65536 count=64 2>/dev/null"]); dt=time.monotonic()-t0; print(f"{len(b)/1e6:.2f} MB in {dt:.3f}s = {len(b)*8/dt/1e6:.1f} Mbps")'
  ```
