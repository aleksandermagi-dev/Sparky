from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


PLUGIN_RE = re.compile(r"(?i)\b[^\r\n<>:\"/\\|?*]+\.(?:esp|esm|esl)\b")
DLL_RE = re.compile(r"(?i)\b([\w .+()-]+\.dll)(?:\+|\b)")
ASSET_RE = re.compile(
    r"(?i)(?:data\\)?(?:meshes|textures|scripts|sound|interface|animations)\\[^\r\n\"<>|]+?\.(?:nif|dds|pex|psc|hkx|wav|xwm|swf)")
FORM_RE = re.compile(r"(?i)\b(?:FormID[:= ]+)?(?:0x)?([0-9A-F]{8})\b")


@dataclass
class CrashFinding:
    title: str
    confidence: str
    explanation: str
    evidence: list[str]
    actions: list[str]


@dataclass
class CrashReport:
    path: Path
    exception: str
    findings: list[CrashFinding]
    assets: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    dlls: list[str] = field(default_factory=list)
    form_ids: list[str] = field(default_factory=list)
    providers: dict[str, list[str]] = field(default_factory=dict)
    active_plugin_matches: list[str] = field(default_factory=list)
    inactive_plugin_mentions: list[str] = field(default_factory=list)


def _unique(values):
    seen = set()
    result = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def find_asset_providers(asset: str, vortex_mods: Path, limit: int = 8) -> list[str]:
    if not vortex_mods.is_dir():
        return []
    rel = re.sub(r"(?i)^data\\", "", asset).replace("\\", "/")
    providers: list[str] = []
    for mod_dir in vortex_mods.iterdir():
        if not mod_dir.is_dir():
            continue
        direct = mod_dir / Path(rel)
        nested = mod_dir / "Data" / Path(rel)
        if direct.is_file() or nested.is_file():
            providers.append(mod_dir.name)
            if len(providers) >= limit:
                break
    return providers


def analyze_crash(path: Path, vortex_mods: Path | None = None, active_names: list[str] | None = None) -> CrashReport:
    text = path.read_text(encoding="utf-8", errors="replace")
    exception_match = re.search(r"(?im)^Unhandled exception[^\r\n]*|^EXCEPTION_[A-Z_]+[^\r\n]*", text)
    exception = exception_match.group(0).strip() if exception_match else "Exception line not found"
    assets = _unique(m.group(0) for m in ASSET_RE.finditer(text))
    plugins = _unique(m.group(0).strip() for m in PLUGIN_RE.finditer(text))
    active_set = {name.casefold() for name in active_names or []}
    active_matches = [name for name in plugins if name.casefold() in active_set]
    inactive_mentions = [name for name in plugins if active_names is not None and name.casefold() not in active_set]
    dlls = _unique(m.group(1).strip() for m in DLL_RE.finditer(text))
    form_ids = _unique("0x" + m.group(1).upper() for m in FORM_RE.finditer(text))
    providers: dict[str, list[str]] = {}
    if vortex_mods:
        for asset in assets[:10]:
            providers[asset] = find_asset_providers(asset, vortex_mods)

    findings: list[CrashFinding] = []
    nif_assets = [a for a in assets if a.lower().endswith(".nif")]
    mesh_markers = ("BSResourceNiBinaryStream", "NiNode", "NiStringExtraData", "NiParticleSystem")
    if nif_assets and sum(marker in text for marker in mesh_markers) >= 2:
        asset = nif_assets[0]
        owner = providers.get(asset, [])
        owner_text = f" Vortex provider found: {', '.join(owner)}." if owner else ""
        findings.append(CrashFinding(
            title="A mesh failed while Skyrim was reading it",
            confidence="High",
            explanation=(
                "The stack contains Bethesda mesh-stream and NetImmerse nodes beside a specific NIF path. "
                "That pattern usually means the mesh is malformed, incompatible, or paired with the wrong skeleton/physics setup."
                + owner_text
            ),
            evidence=[asset, *[m for m in mesh_markers if m in text]],
            actions=[
                "In Vortex, identify the mod supplying the listed mesh and reinstall or replace that file.",
                "Check that the mesh matches the installed body, skeleton, and physics setup.",
                "Temporarily disable only that mesh replacer and reproduce the same scene before changing unrelated plugins.",
            ],
        ))

    lower = text.casefold()
    physics = [d for d in dlls if any(x in d.casefold() for x in ("hdt", "smp", "fasterhdt"))]
    if physics and ("nif" in lower or "ninode" in lower):
        findings.append(CrashFinding(
            title="Physics compatibility deserves a secondary check",
            confidence="Medium",
            explanation="A physics DLL is loaded and the crash involves mesh objects. This is supporting evidence, not proof that the DLL itself is broken.",
            evidence=physics[:4],
            actions=["Confirm the physics plugin version supports the installed Skyrim runtime.", "Check the implicated outfit/body asset for matching physics configuration files."],
        ))

    if not findings:
        stack_dlls = [d for d in dlls if d.casefold() not in {"skyrimse.exe", "skse64.dll"}]
        findings.append(CrashFinding(
            title="No single high-confidence signature was found",
            confidence="Low",
            explanation="The access violation alone does not identify a guilty mod. The named DLLs, plugins, assets, and FormIDs are leads rather than verdicts.",
            evidence=(assets[:3] + plugins[:3] + stack_dlls[:3]) or [exception],
            actions=["Compare two or more logs from the same reproducible crash.", "Test the smallest relevant group of recently changed mods rather than disabling the entire load order."],
        ))
    return CrashReport(path, exception, findings, assets, plugins, dlls, form_ids, providers, active_matches, inactive_mentions)


def render_crash_report(report: CrashReport) -> str:
    out = [f"SPARKY CRASH TRANSLATION", f"Log: {report.path}", f"Exception: {report.exception}", ""]
    for index, finding in enumerate(report.findings, 1):
        out.extend([
            f"{index}. {finding.title} [{finding.confidence} confidence]",
            finding.explanation,
            "Evidence:", *[f"  - {x}" for x in finding.evidence],
            "Recommended next steps:", *[f"  - {x}" for x in finding.actions], "",
        ])
    if report.active_plugin_matches:
        out.extend(["Plugins named in the log that are active now:", *[f"  - {name}" for name in report.active_plugin_matches[:20]], ""])
    if report.inactive_plugin_mentions:
        out.extend(["Plugins named in the log but not active now (the load order may have changed):", *[f"  - {name}" for name in report.inactive_plugin_mentions[:10]], ""])
    out.append("Sparky reports correlations, not absolute blame. Preserve the original log and change one thing at a time.")
    return "\n".join(out)
