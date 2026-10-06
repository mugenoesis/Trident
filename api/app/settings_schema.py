"""Builds the overridable-settings schema for GET /settings/schema.

Preferred path: `--help-json` (docs/ARCHITECTURE.md patch #5, not yet
landed upstream/on our fork as of this scaffold) gives full structured
option metadata directly from `ConfigDef`. Until that patch exists, we
fall back to best-effort parsing of `--help-fff`/`--help-sla` text.

The text fallback's exact regex will need truing up against real CLI
output once vendor/orcaslicer is built (M1) — OrcaSlicer's help text
format isn't nailed down without a live binary. Treat parse failures as
"skip that line", not fatal.
"""
from __future__ import annotations

import re
import subprocess

from .blocked_settings import BLOCKED_SETTINGS
from .cli_runner import fetch_help_json
from .config import settings
from .schemas import SettingDef, SettingsSchema

# e.g. "  --layer-height <float>   Layer height in mm (default: 0.2)"
_HELP_LINE_RE = re.compile(
    r"^\s*--(?P<key>[a-zA-Z0-9][a-zA-Z0-9-]*)"
    r"(?:\s*<(?P<type>[a-zA-Z]+)>)?"
    r"\s+(?P<desc>.*?)"
    r"(?:\(default:\s*(?P<default>[^)]*)\))?\s*$"
)


def _parse_help_text(text: str) -> list[SettingDef]:
    out: list[SettingDef] = []
    for line in text.splitlines():
        m = _HELP_LINE_RE.match(line)
        if not m:
            continue
        key = m.group("key").replace("-", "_")
        out.append(
            SettingDef(
                key=key,
                type=m.group("type") or "string",
                description=(m.group("desc") or "").strip() or None,
                default=m.group("default"),
            )
        )
    return out


def _fetch_help_text(flag: str) -> str:
    proc = subprocess.run(
        [settings.orcaslicer_bin, flag], capture_output=True, text=True, timeout=10
    )
    return proc.stdout


def build_settings_schema() -> SettingsSchema:
    help_json = fetch_help_json()
    if help_json is not None:
        defs = [
            SettingDef(
                key=item["key"],
                type=item.get("type", "string"),
                label=item.get("label"),
                description=item.get("description"),
                enum_values=item.get("enum_values"),
                enum_labels=item.get("enum_labels"),
                default=item.get("default"),
            )
            for item in help_json
            if item.get("key") not in BLOCKED_SETTINGS
        ]
        return SettingsSchema(source="help-json", settings=defs)

    defs_by_key: dict[str, SettingDef] = {}
    for flag in ("--help-fff", "--help-sla"):
        try:
            text = _fetch_help_text(flag)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for d in _parse_help_text(text):
            if d.key not in BLOCKED_SETTINGS:
                defs_by_key.setdefault(d.key, d)

    return SettingsSchema(source="help-text-fallback", settings=list(defs_by_key.values()))
