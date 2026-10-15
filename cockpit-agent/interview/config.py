"""Portable server configuration; never read a neighbouring project's secrets."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ENV_NAMES = {
    "COCKPIT_API_BASE", "COCKPIT_API_KEY", "COCKPIT_API_FILE", "COCKPIT_MODEL",
    "COCKPIT_VISION_MODEL", "COCKPIT_PHOTON_URL", "COCKPIT_OVERPASS_URL", "COCKPIT_OSRM_URL",
}


class ConfigurationError(ValueError):
    """Only fixed, credential-free messages may leave this configuration layer."""


@dataclass(frozen=True)
class ApiCredentials:
    base_url: str
    key: str = field(repr=False)


def load_project_env(path: Path | None = None) -> None:
    """Read a small, literal KEY=value .env subset without shell execution.

    Existing process environment wins, including explicitly empty values. Only
    the documented COCKPIT variables are accepted. Quotes are optional; there is
    no interpolation, multiline value, command substitution or escape decoding.
    """
    source = path if path is not None else ROOT / ".env"
    try:
        raw = source.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return
    except (OSError, UnicodeError):
        raise ConfigurationError("无法读取项目根目录的 .env 配置。") from None
    pending = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ConfigurationError(".env 格式无效，请使用每行一个 KEY=value 配置。")
        if name not in ENV_NAMES:
            continue
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigurationError(".env 中存在未闭合的引号。")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        pending[name] = value
    # Parse the entire file before modifying the process environment.
    for name, value in pending.items():
        os.environ.setdefault(name, value)


def api_credentials(credential_path: str | Path | None = None) -> ApiCredentials:
    """Use an explicit file, otherwise environment credentials, then opt-in file."""
    base, key = "", ""
    file_name = credential_path
    if file_name is None:
        base = os.getenv("COCKPIT_API_BASE", "").strip()
        key = os.getenv("COCKPIT_API_KEY", "").strip()
        if base or key:
            if not base or not key:
                raise ConfigurationError("请同时设置 COCKPIT_API_BASE 和 COCKPIT_API_KEY。")
        else:
            file_name = os.getenv("COCKPIT_API_FILE", "").strip() or None
    if file_name is not None:
        path = Path(file_name).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        try:
            raw = path.read_text(encoding="utf-8")
            url_match = re.search(r"https?://[^\s]+", raw)
            key_match = re.search(r"sk-[A-Za-z0-9_\-]+", raw)
            if not url_match or not key_match:
                raise ValueError()
            base, key = url_match.group(0), key_match.group(0)
        except (OSError, UnicodeError, ValueError):
            raise ConfigurationError("无法读取 COCKPIT_API_FILE；文件须包含服务 URL 和 sk- 格式密钥。") from None
    if not base or not key:
        raise ConfigurationError("尚未配置模型服务；请设置 COCKPIT_API_BASE 和 COCKPIT_API_KEY，或使用离线规则模式。")
    try:
        url = urlsplit(base)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c.isspace() for c in base)):
            raise ValueError()
        # Accessing port also rejects malformed URLs such as an invalid port.
        _ = url.port
    except ValueError:
        raise ConfigurationError("COCKPIT_API_BASE 必须是有效的 HTTP(S) 服务地址，不能含用户名、密码或查询参数。") from None
    if any(c.isspace() for c in key):
        raise ConfigurationError("COCKPIT_API_KEY 不能包含空白字符。")
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return ApiCredentials(base_url=base + "/", key=key)
