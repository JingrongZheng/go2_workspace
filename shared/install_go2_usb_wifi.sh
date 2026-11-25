#!/usr/bin/env bash
# Run on the Go2 expansion computer with sudo, after building EXP-0007's driver.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run this script with sudo.' >&2; exit 1; }
kernel_release=$(uname -r)
[[ $kernel_release == 5.10.104-tegra && $(uname -m) == aarch64 ]] || { echo 'Unsupported kernel/architecture.' >&2; exit 1; }
module_file=${1:?Usage: sudo bash install_go2_usb_wifi.sh /absolute/path/88x2cu.ko}
[[ $(modinfo -F vermagic "$module_file") == "$kernel_release "* ]] || { echo 'Kernel mismatch.' >&2; exit 1; }
modinfo -F alias "$module_file" | grep -q 'usb:v0BDApC812' || { echo 'Wrong USB driver.' >&2; exit 1; }
install -D -m 0644 "$module_file" "/lib/modules/$kernel_release/updates/go2/88x2cu.ko"
install -d /usr/local/libexec
cat > /usr/local/libexec/go2-usb-wifi-bind <<'BIND'
#!/bin/bash
set -euo pipefail
iface=${1:?USB interface required}
[[ $iface =~ ^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$ ]] || exit 1
node=/sys/bus/usb/devices/$iface
parent=/sys/bus/usb/devices/${iface%:*}
[[ -d $node ]] || exit 0
[[ $(cat "$parent/idVendor") == 0bda && $(cat "$parent/idProduct") == c812 ]] || exit 1
[[ $(cat "$node/bInterfaceClass") == ff ]] || exit 1
modprobe 88x2cu
bound=$(basename "$(readlink -f "$node/driver")")
[[ $bound == rtl88x2cu ]] && exit 0
if [[ -L $node/driver ]]; then
    [[ $bound == option ]] || { echo "Unexpected driver: $bound" >&2; exit 1; }
    printf '%s' "$iface" > /sys/bus/usb/drivers/option/unbind
fi
# Loading the module can already have bound an unclaimed interface.
[[ $(basename "$(readlink -f "$node/driver")") == rtl88x2cu ]] && exit 0
if ! printf '%s' "$iface" > /sys/bus/usb/drivers/rtl88x2cu/bind; then
    if [[ $bound == option ]]; then
        printf '%s' "$iface" > /sys/bus/usb/drivers/option/bind || true
    fi
    exit 1
fi
BIND
chmod 0755 /usr/local/libexec/go2-usb-wifi-bind
cat > /etc/modprobe.d/go2-usb-wifi.conf <<'CONF'
options 88x2cu rtw_power_mgnt=0 rtw_enusbss=0
CONF
cat > /etc/modules-load.d/go2-usb-wifi.conf <<'CONF'
88x2cu
CONF
cat > /etc/systemd/system/go2-usb-wifi-bind@.service <<'UNIT'
[Unit]
Description=Bind Go2 Realtek USB WiFi interface %I
After=systemd-modules-load.service

[Service]
Type=oneshot
ExecStart=/usr/local/libexec/go2-usb-wifi-bind %I
TimeoutStartSec=30
UNIT
cat > /etc/udev/rules.d/80-go2-usb-wifi.rules <<'RULE'
ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_interface", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="c812", ATTR{bInterfaceClass}=="ff", TAG+="systemd", ENV{SYSTEMD_WANTS}+="go2-usb-wifi-bind@%k.service"
RULE
depmod -a "$kernel_release"
systemctl daemon-reload
udevadm control --reload-rules
modprobe 88x2cu
# Handle an adapter that was already present before installation.
for parent in /sys/bus/usb/devices/*; do
    [[ -f $parent/idVendor && -f $parent/idProduct ]] || continue
    [[ $(cat "$parent/idVendor") == 0bda && $(cat "$parent/idProduct") == c812 ]] || continue
    for node in "$parent":*; do
        [[ -f $node/bInterfaceClass && $(cat "$node/bInterfaceClass") == ff ]] || continue
        systemctl start "go2-usb-wifi-bind@${node##*/}.service"
    done
done
echo 'Installed for 5.10.104-tegra. Insert the 0bda:c812 adapter, then check nmcli device status.'
