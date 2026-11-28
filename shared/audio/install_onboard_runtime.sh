#!/usr/bin/env bash
# Run inside ~/go2-dialogue after receiving code/vendor/wheels. No sudo or apt.
set -euo pipefail
go2_dialogue_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$go2_dialogue_root"
umask 077
mkdir -p .work
python3 -m venv --without-pip .venv
# Ubuntu may lack ensurepip. Execute pip directly from its pure Python wheel.
go2_pip_wheel="$go2_dialogue_root/wheels/pip-25.0.1-py3-none-any.whl"
PYTHONPATH="$go2_pip_wheel" .venv/bin/python -m pip install --no-index --find-links wheels pip==25.0.1
.venv/bin/python -m pip install --no-index --find-links wheels -r shared/audio/requirements-onboard.txt
if [[ -f libportaudio2_arm64.deb ]]; then
  dpkg-deb -x libportaudio2_arm64.deb .work/system-libs
  ln -sfn libportaudio.so.2 .work/system-libs/usr/lib/aarch64-linux-gnu/libportaudio.so
fi
if [[ ! -f .work/dialogue.env ]]; then
  cat > .work/dialogue.env <<'ENV'
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k3.1-pro
LLM_REASONING_EFFORT=low
LLM_API_KEY=
ENV
fi
chmod 600 .work/dialogue.env
bash shared/audio/run_onboard_dialogue.sh --help >/dev/null
printf '%s\n' 'Onboard runtime installed; cloud and speaker are not yet verified.'
