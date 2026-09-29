from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkyrimPaths:
    data: Path
    plugins_txt: Path
    loadorder_txt: Path
    crashlogs: Path
    vortex_mods: Path

    @classmethod
    def detect(cls) -> "SkyrimPaths":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        roaming = Path(os.environ.get("APPDATA", ""))
        documents = Path.home() / "Documents"
        configured = os.environ.get("SKYRIM_DATA")
        candidates = [
            *([Path(configured)] if configured else []),
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition\Data"),
            Path(r"C:\Program Files\Steam\steamapps\common\Skyrim Special Edition\Data"),
        ]
        data = next((p for p in candidates if p.is_dir()), candidates[0])
        profile = local / "Skyrim Special Edition"
        return cls(
            data=data,
            plugins_txt=profile / "plugins.txt",
            loadorder_txt=profile / "loadorder.txt",
            crashlogs=documents / "My Games" / "Skyrim Special Edition" / "SKSE" / "Crashlogs",
            vortex_mods=roaming / "Vortex" / "skyrimse" / "mods",
        )

    def latest_crash(self) -> Path | None:
        if not self.crashlogs.is_dir():
            return None
        logs = list(self.crashlogs.glob("*.log"))
        return max(logs, key=lambda p: p.stat().st_mtime) if logs else None

    @classmethod
    def from_settings(cls, path: Path) -> "SkyrimPaths":
        detected = cls.detect()
        if not path.is_file():
            return detected
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{key: Path(saved.get(key, str(getattr(detected, key)))) for key in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return detected

    def save_settings(self, path: Path) -> None:
        path.write_text(json.dumps({key: str(getattr(self, key)) for key in self.__dataclass_fields__}, indent=2), encoding="utf-8")


def read_active_plugins(path: Path) -> list[str]:
    if not path.is_file():
        return []
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("*") and len(line) > 1:
            names.append(line[1:].strip())
    return names
