"""iFlytek streaming TTS core for dialogue; credentials remain in private config."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import ssl
from dataclasses import dataclass
from email.utils import formatdate
from pathlib import Path
from typing import AsyncIterator, Dict, Optional
from urllib.parse import urlencode, urlparse

DEFAULT_CLONE_URL = "wss://cn-huabei-1.xf-yun.com/v1/private/voice_clone"
DEFAULT_STANDARD_URL = "wss://tts-api.xfyun.cn/v2/tts"
DEFAULT_ENV_RELPATH = ".work/xfyun.env"
DEFAULT_VOICES_RELPATH = ".work/xfyun_voices.json"

@dataclass
class XfyunConfig:
    app_id: str
    api_key: str
    api_secret: str
    engine: str = "clone"  # "clone" | "standard"
    res_id: str = ""       # required when engine == "clone"
    vcn: str = "x5_clone"  # x5_clone (standard clone) | x6_clone (multi-style) | xiaoyan ...
    url: str = ""
    speed: int = 50
    volume: int = 50
    pitch: int = 50
    sample_rate: int = 24000
    dup_first_char: bool = True  # repeat first char for clone engine to prevent first-char drop

    def resolved_url(self) -> str:
        if self.url:
            return self.url
        return DEFAULT_CLONE_URL if self.engine == "clone" else DEFAULT_STANDARD_URL

def find_workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]

def load_env_file(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Parse KEY=VALUE lines from an env file without mutating os.environ."""
    path = env_path or (find_workspace_root() / DEFAULT_ENV_RELPATH)
    loaded: Dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        loaded[key] = val
    return loaded

def load_voice_aliases(voices_path: Optional[Path] = None) -> Dict[str, str]:
    """Load short voice alias -> iFlytek res_id map from .work/xfyun_voices.json."""
    path = voices_path or (find_workspace_root() / DEFAULT_VOICES_RELPATH)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}

def resolve_xfyun_config(
    *,
    env_file: Optional[Path] = None,
    engine: Optional[str] = None,
    vcn: Optional[str] = None,
    res_id: Optional[str] = None,
    voice: Optional[str] = None,
    url: Optional[str] = None,
    speed: Optional[int] = None,
    volume: Optional[int] = None,
    pitch: Optional[int] = None,
    sample_rate: Optional[int] = None,
    dup_first_char: Optional[bool] = None,
) -> XfyunConfig:
    file_env = load_env_file(env_file)
    aliases = load_voice_aliases()

    def pick(name: str, default: str = "") -> str:
        val = os.environ.get(name)
        if val is not None and val != "":
            return val
        return file_env.get(name, default)

    resolved_engine = (engine or pick("XFYUN_ENGINE", "clone")).strip().lower()
    if resolved_engine not in ("clone", "standard"):
        raise ValueError(f"Unsupported XFYUN engine: {resolved_engine!r} (use 'clone' or 'standard').")

    default_vcn = "x5_clone" if resolved_engine == "clone" else "xiaoyan"
    resolved_vcn = vcn or pick("XFYUN_VCN", default_vcn)

    if voice:
        if voice in aliases:
            resolved_res_id = aliases[voice]
        else:
            known = ", ".join(sorted(aliases)) or "(none)"
            raise ValueError(f"Unknown voice alias {voice!r}. Known aliases: {known}")
    else:
        raw_res_id = res_id if res_id is not None else pick("XFYUN_RES_ID", "")
        resolved_res_id = aliases.get(raw_res_id, raw_res_id)

    resolved_url = url or pick("XFYUN_TTS_URL", "")
    resolved_sr = int(sample_rate or pick("XFYUN_SAMPLE_RATE", "24000" if resolved_engine == "clone" else "16000"))

    resolved_dup = (
        dup_first_char
        if dup_first_char is not None
        else (resolved_engine == "clone")
    )

    cfg = XfyunConfig(
        app_id=pick("XFYUN_APP_ID"),
        api_key=pick("XFYUN_API_KEY"),
        api_secret=pick("XFYUN_API_SECRET"),
        engine=resolved_engine,
        res_id=resolved_res_id,
        vcn=resolved_vcn,
        url=resolved_url,
        speed=int(speed if speed is not None else pick("XFYUN_SPEED", "50")),
        volume=int(volume if volume is not None else pick("XFYUN_VOLUME", "50")),
        pitch=int(pitch if pitch is not None else pick("XFYUN_PITCH", "50")),
        sample_rate=resolved_sr,
        dup_first_char=resolved_dup,
    )
    return cfg

def preprocess_tts_text(cfg: XfyunConfig, text: str) -> str:
    """Optionally repeat the first non-whitespace character to compensate for first-char clipping."""
    stripped = text.strip()
    if not stripped or not cfg.dup_first_char:
        return text
    return stripped[0] + stripped

def validate_config(cfg: XfyunConfig) -> None:
    missing = []
    if not cfg.app_id:
        missing.append("XFYUN_APP_ID")
    if not cfg.api_key:
        missing.append("XFYUN_API_KEY")
    if not cfg.api_secret:
        missing.append("XFYUN_API_SECRET")
    if cfg.engine == "clone" and not cfg.res_id:
        missing.append("XFYUN_RES_ID")
    if missing:
        env_path = find_workspace_root() / DEFAULT_ENV_RELPATH
        raise ValueError(
            f"Missing iFlytek credentials: {', '.join(missing)}. "
            f"Set them as environment variables or put them in {env_path}."
        )

def build_signed_ws_url(
    base_url: str,
    api_key: str,
    api_secret: str,
    *,
    timestamp: Optional[float] = None,
) -> str:
    """Build iFlytek HMAC-SHA256 authenticated WebSocket URL."""
    parsed = urlparse(base_url)
    host = parsed.hostname
    path = parsed.path or "/"
    if not host:
        raise ValueError(f"Invalid WebSocket URL: {base_url!r}")

    date_str = formatdate(timeval=timestamp, usegmt=True)
    signature_origin = f"host: {host}\ndate: {date_str}\nGET {path} HTTP/1.1"
    digest = hmac.new(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature_b64 = base64.b64encode(digest).decode("ascii")
    auth_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature_b64}"'
    )
    auth_b64 = base64.b64encode(auth_origin.encode("utf-8")).decode("ascii")
    query = urlencode({"authorization": auth_b64, "date": date_str, "host": host})
    return f"{base_url}?{query}"

def build_clone_request(cfg: XfyunConfig, text: str, *, encoding: str = "raw") -> dict:
    """Build JSON request for iFlytek One-Sentence Voice Clone TTS (x5_clone / x6_clone)."""
    return {
        "header": {
            "app_id": cfg.app_id,
            "status": 2,
            "res_id": cfg.res_id,
        },
        "parameter": {
            "tts": {
                "vcn": cfg.vcn,
                "volume": cfg.volume,
                "rhy": 0,
                "pybuffer": 1,
                "speed": cfg.speed,
                "pitch": cfg.pitch,
                "bgs": 0,
                "reg": 0,
                "rdn": 0,
                "audio": {
                    "encoding": encoding,
                    "sample_rate": cfg.sample_rate,
                    "channels": 1,
                    "bit_depth": 16,
                    "frame_size": 0,
                },
            }
        },
        "payload": {
            "text": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "plain",
                "status": 2,
                "seq": 0,
                "text": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            }
        },
    }

def build_standard_request(cfg: XfyunConfig, text: str) -> dict:
    """Build JSON request for iFlytek standard v2 WebSocket TTS (raw 16-bit PCM)."""
    auf = f"audio/L16;rate={cfg.sample_rate}"
    return {
        "common": {"app_id": cfg.app_id},
        "business": {
            "aue": "raw",
            "auf": auf,
            "vcn": cfg.vcn,
            "speed": cfg.speed,
            "volume": cfg.volume,
            "pitch": cfg.pitch,
            "tte": "UTF8",
        },
        "data": {
            "status": 2,
            "text": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        },
    }

async def stream_pcm_chunks(
    cfg: XfyunConfig,
    text: str,
    *,
    timeout: float = 30.0,
    insecure_ssl: bool = False,
) -> AsyncIterator[bytes]:
    """Stream raw 16-bit mono PCM chunks from iFlytek WebSocket TTS."""
    import aiohttp

    validate_config(cfg)
    if not text.strip():
        raise ValueError("Synthesis text must not be empty.")

    ws_url = build_signed_ws_url(cfg.resolved_url(), cfg.api_key, cfg.api_secret)
    ssl_ctx = ssl.create_default_context()
    if insecure_ssl:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    effective_text = preprocess_tts_text(cfg, text)
    payload = (
        build_clone_request(cfg, effective_text, encoding="raw")
        if cfg.engine == "clone"
        else build_standard_request(cfg, effective_text)
    )

    try:
        client_timeout = aiohttp.ClientTimeout(total=None, sock_connect=timeout, sock_read=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout, trust_env=True) as session:
            async with session.ws_connect(
                ws_url,
                ssl=ssl_ctx if ws_url.startswith("wss://") else False,
                max_msg_size=16 * 1024 * 1024,
            ) as ws:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))
                while True:
                    ws_msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                    if ws_msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                        break
                    if ws_msg.type == aiohttp.WSMsgType.ERROR:
                        raise RuntimeError(f"WebSocket error: {ws.exception()}")
                    if ws_msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    msg = json.loads(ws_msg.data)

                    if cfg.engine == "clone":
                        # Support both {header:{code,status}, payload:{audio:{audio,status}}}
                        # and {code, data:{audio,status}} variants returned by iFlytek clusters.
                        if "header" in msg:
                            code = msg["header"].get("code", -1)
                            err_msg = msg["header"].get("message", "")
                            if code != 0:
                                raise RuntimeError(f"iFlytek voice_clone error {code}: {err_msg}")
                            audio_obj = msg.get("payload", {}).get("audio", {})
                            audio_b64 = audio_obj.get("audio")
                            status = audio_obj.get("status", msg["header"].get("status"))
                        else:
                            code = msg.get("code", -1)
                            err_msg = msg.get("message", "")
                            if code != 0:
                                raise RuntimeError(f"iFlytek voice_clone error {code}: {err_msg}")
                            data_obj = msg.get("data", {})
                            audio_b64 = data_obj.get("audio")
                            status = data_obj.get("status")
                    else:
                        code = msg.get("code", -1)
                        err_msg = msg.get("message", "")
                        if code != 0:
                            raise RuntimeError(f"iFlytek TTS error {code}: {err_msg}")
                        data_obj = msg.get("data", {})
                        audio_b64 = data_obj.get("audio")
                        status = data_obj.get("status")

                    if audio_b64:
                        chunk = base64.b64decode(audio_b64)
                        if chunk:
                            yield chunk

                    if status == 2:
                        break
    except Exception as exc:
        err_str = str(exc)
        if "401" in err_str or "403" in err_str or "HMAC" in err_str:
            now_gmt = formatdate(usegmt=True)
            raise RuntimeError(
                f"iFlytek WebSocket auth failed ({exc}). "
                f"Check XFYUN_API_KEY / XFYUN_API_SECRET and system UTC clock "
                f"(current local Date header: {now_gmt}; iFlytek rejects clock skew > 5 min)."
            ) from exc
        raise
