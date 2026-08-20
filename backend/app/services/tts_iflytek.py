"""
iFLYTEK Online TTS, synchronous WebSocket client.
Run via ThreadPoolExecutor; do not call from async context directly.
"""

import base64
import hashlib
import hmac
import json
import ssl
import threading
from email.utils import formatdate
from urllib.parse import urlencode

import websocket

_HOST    = "tts-api-sg.xf-yun.com"
_PATH    = "/v2/tts"
_WS_URL  = f"wss://{_HOST}{_PATH}"
_TIMEOUT = 20.0  # hard wall-clock limit per synthesis call

_VALID_VCNS = {
    "x_xiaoyan", "x_xiaolin", "x_xiaomei", "x_xiaoxue",
    "x_xiaoxi",  "x_xiaoyuan","x_xiaofeng","x_yifeng",
    "x_laoma",   "x4_lingfeizhe_assist", "x4_lingxiaoqi_assist",
    "x4_ziwen_assist", "x4_yilin", "x3_xiaoyue",
}
_DEFAULT_VCN = "x_xiaoyan"

# Minimum valid MP3 size, unauthorized voices return ~864 B header-only file
_MIN_AUDIO_BYTES = 1024


def _build_url(api_key: str, api_secret: str) -> str:
    date = formatdate(usegmt=True)
    sig_origin = f"host: {_HOST}\ndate: {date}\nGET {_PATH} HTTP/1.1"
    sig = hmac.new(api_secret.encode(), sig_origin.encode(), digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(sig).decode()
    auth_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(auth_origin.encode()).decode()
    return f"{_WS_URL}?{urlencode({'authorization': authorization, 'date': date, 'host': _HOST})}"


def synthesize(
    text: str,
    rate: float,
    vcn: str,
    appid: str,
    api_key: str,
    api_secret: str,
) -> bytes:
    """
    Blocking TTS call via iFLYTEK WebSocket.
    Returns raw MP3 bytes. Raises RuntimeError on failure or timeout.
    vcn: iFLYTEK voice name (e.g. "x_xiaoyan"); unknown names fall back to default.
    rate: browser-style 0.5–2.0 → mapped to iFLYTEK 0-100 speed
    """
    if vcn not in _VALID_VCNS:
        vcn = _DEFAULT_VCN
    # iFLYTEK speed: 0-100, default 50; map browser rate 0.5→25, 1.0→50, 2.0→100
    iflytek_speed = max(0, min(100, int(50 + (rate - 1.0) * 50)))

    chunks: list[bytes] = []
    errors: list[str] = []

    def on_open(ws):
        payload = {
            "common": {"app_id": appid},
            "business": {
                "aue":    "lame",
                "auf":    "audio/L16;rate=16000",
                "vcn":    vcn,
                "speed":  iflytek_speed,
                "volume": 50,
                "pitch":  50,
                "bgs":    0,
                "tte":    "utf8",
            },
            "data": {
                "status": 2,
                "text":   base64.b64encode(text.encode("utf-8")).decode(),
            },
        }
        ws.send(json.dumps(payload))

    def on_message(ws, message):
        msg = json.loads(message)
        if msg.get("code", -1) != 0:
            errors.append(msg.get("message", "unknown error"))
            ws.close()
            return
        audio = msg.get("data", {}).get("audio", "")
        if audio:
            chunks.append(base64.b64decode(audio))
        if msg.get("data", {}).get("status") == 2:
            ws.close()

    def on_error(ws, err):
        errors.append(str(err))
        ws.close()  # ensure connection is released on error

    url = _build_url(api_key, api_secret)
    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=lambda *_: None,
    )

    # Force-close after _TIMEOUT seconds to prevent indefinite blocking
    timer = threading.Timer(_TIMEOUT, lambda: (errors.append("iFLYTEK TTS timed out"), ws.close()))
    timer.start()
    try:
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_REQUIRED})
    finally:
        timer.cancel()

    if errors:
        raise RuntimeError(f"iFLYTEK TTS error: {errors[0]}")
    if not chunks:
        raise RuntimeError("iFLYTEK TTS returned empty audio")

    audio = b"".join(chunks)
    if len(audio) < _MIN_AUDIO_BYTES:
        raise RuntimeError(f"iFLYTEK voice '{vcn}' not authorized on this AppID")

    return audio
