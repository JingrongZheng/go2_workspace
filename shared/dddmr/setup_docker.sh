#!/usr/bin/env bash
# Run in the user's own PC terminal so sudo authentication stays local.
set -euo pipefail
[[ $(id -u) != 0 ]] || { echo 'Run as your normal desktop user.' >&2; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(dpkg --print-architecture) == amd64 ]] || {
  echo 'This entry was prepared for Ubuntu 22.04 amd64.' >&2; exit 1;
}
sudo -v
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
if ! command -v docker >/dev/null; then
  if dpkg-query -W -f='${Status}' docker.io 2>/dev/null | grep -q 'install ok installed'; then
    echo 'An Ubuntu Docker package is installed but its CLI is missing; inspect first.' >&2
    exit 1
  fi
  sudo install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    sudo curl -fsSL --retry 3 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
  fi
  if [[ ! -f /etc/apt/sources.list.d/docker.sources && ! -f /etc/apt/sources.list.d/docker.list ]]; then
    sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  fi
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo systemctl enable --now docker
sudo usermod -aG docker "$(id -un)"

# Configure access to the already-installed host GPU driver; do not install a driver.
if ! command -v nvidia-ctk >/dev/null; then
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  curl -fsSL --retry 3 https://nvidia.github.io/libnvidia-container/gpgkey -o "$work/nvidia.asc"
  gpg --batch --yes --dearmor -o "$work/nvidia.gpg" "$work/nvidia.asc"
  sudo install -m 0644 "$work/nvidia.gpg" /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL --retry 3 https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list -o "$work/nvidia.list"
  if [[ ! -f /etc/apt/sources.list.d/nvidia-container-toolkit.list ]]; then
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' "$work/nvidia.list" |
      sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  fi
  sudo apt-get update
  sudo apt-get install -y nvidia-container-toolkit
fi
if [[ -f /etc/docker/daemon.json ]]; then
  sudo cp -n /etc/docker/daemon.json /etc/docker/daemon.json.before-dddmr
fi
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo docker version
sudo docker info --format 'Docker server: {{.ServerVersion}}; runtimes: {{json .Runtimes}}'
echo 'Docker setup finished. Tell Codex to continue; no DDDMR image was built here.'
