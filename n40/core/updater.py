"""Проверка обновлений через GitHub Releases."""

from __future__ import annotations

import json
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import GITHUB_REPO, __version__

API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    page_url: str
    installer_url: str | None
    installer_name: str | None


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _parse_version(remote) > _parse_version(local)


def fetch_latest(repo: str = GITHUB_REPO, timeout: float = 10.0) -> ReleaseInfo | None:
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "N40-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — нет сети / нет релизов
        return None
    exes = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")]
    asset = next((a for a in exes if "setup" in a["name"].lower()), exes[0] if exes else None)
    return ReleaseInfo(
        version=data.get("tag_name", "0"),
        notes=data.get("body") or "",
        page_url=data.get("html_url", f"https://github.com/{repo}/releases"),
        installer_url=asset.get("browser_download_url") if asset else None,
        installer_name=asset.get("name") if asset else None,
    )


def download(info: ReleaseInfo, progress=None) -> Path:
    if not info.installer_url:
        raise RuntimeError("В релизе нет установщика")
    target = Path(tempfile.gettempdir()) / (info.installer_name or "N40-Setup.exe")
    req = urllib.request.Request(info.installer_url, headers={"User-Agent": "N40-updater"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(65536):
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return target
