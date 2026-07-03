import os
import re
from pathlib import Path

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "deploy" / "mediamtx" / "mediamtx.yml"
MEDIAMTX_CONFIG_PATH = os.getenv("MEDIAMTX_CONFIG_PATH", str(_DEFAULT_CONFIG_PATH))


def write_mediamtx_host_config(host: str) -> None:
    """
    Update webrtcIPsFromInterfaces and webrtcAdditionalHosts in mediamtx.yml.

    When host is set: disables interface scanning and pins the single host as
    the advertised ICE candidate. When host is cleared: restores interface
    scanning and empties the additional hosts list.

    Uses line-by-line replacement to avoid reparsing the full YAML file,
    which would destroy comments and formatting.
    """
    with open(MEDIAMTX_CONFIG_PATH, "r") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if re.match(r'\s*webrtcIPsFromInterfaces:', line):
            val = "no" if host else "yes"
            new_lines.append(f"webrtcIPsFromInterfaces: {val}\n")
        elif re.match(r'\s*webrtcAdditionalHosts:', line):
            val = f'["{host}"]' if host else "[]"
            new_lines.append(f"webrtcAdditionalHosts: {val}\n")
        else:
            new_lines.append(line)

    with open(MEDIAMTX_CONFIG_PATH, "w") as f:
        f.writelines(new_lines)
