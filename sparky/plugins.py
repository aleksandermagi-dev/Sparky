from __future__ import annotations

import struct
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


TES4_MASTER = 0x00000001
TES4_LIGHT = 0x00000200
RISKY_RECORDS = {
    "ACHR", "CELL", "DIAL", "INFO", "LAND", "NAVM", "PACK", "PHZD",
    "QUST", "REFR", "SCEN", "WRLD",
}
BUILTIN_FULL_PLUGINS = ("Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm")
FULL_SLOT_LIMIT = 254
# Filename identity matters for frameworks even when their ESP contains only overrides.
PROTECTED_FRAMEWORK = re.compile(r"(?<![a-z0-9])(?:xpmse|xpmsse|xp32)(?![a-z0-9])", re.IGNORECASE)
MERGE_RECORDS = {
    "ALCH", "AMMO", "ARMA", "ARMO", "AVIF", "BOOK", "COBJ", "ENCH",
    "FLST", "GLOB", "GMST", "INGR", "KYWD", "LIGH", "LVLI", "LVLN",
    "LVSP", "MATO", "MESG", "MISC", "PERK", "SNDR", "SOUN", "SPEL",
    "STAT", "TXST", "WEAP",
}
# Flag-only copies preserve record payloads, filenames and asset routing.
# These additional override types do not need to be supported by the merge writer.
ESL_OVERRIDE_RECORDS = MERGE_RECORDS | {"CLFM", "IDLE", "NPC_"}


@dataclass
class PluginInfo:
    name: str
    path: Path
    flags: int = 0
    masters: list[str] = field(default_factory=list)
    records: Counter[str] = field(default_factory=Counter)
    has_vmad: bool = False
    has_archive: bool = False
    error: str | None = None
    depended_on_by: list[str] = field(default_factory=list)
    form_ids: list[int] = field(default_factory=list)
    flat_groups: bool = True

    @property
    def is_master(self) -> bool:
        return bool(self.flags & TES4_MASTER) or self.path.suffix.lower() == ".esm"

    @property
    def is_light(self) -> bool:
        return bool(self.flags & TES4_LIGHT) or self.path.suffix.lower() == ".esl"

    @property
    def record_count(self) -> int:
        return sum(self.records.values())

    @property
    def new_record_count(self) -> int:
        return sum((form_id >> 24) >= len(self.masters) for form_id in self.form_ids)

    @property
    def esl_compatible_ids(self) -> bool:
        return all((form_id & 0xFFFFFF) <= 0xFFF for form_id in self.form_ids if (form_id >> 24) >= len(self.masters))


@dataclass
class PluginAssessment:
    plugin: PluginInfo
    merge_candidate: bool
    esl_review_candidate: bool
    reasons: list[str]
    merge_ready: bool = False
    esl_ready: bool = False
    esl_status: str = "protected_or_blocked"


@dataclass
class LoadOrderReport:
    plugins: list[PluginInfo]
    assessments: list[PluginAssessment]
    missing: list[str]
    builtin_full: list[str] = field(default_factory=list)

    @property
    def full_count(self) -> int:
        return sum(not p.is_light for p in self.plugins) + len(self.builtin_full)

    @property
    def light_count(self) -> int:
        return sum(p.is_light for p in self.plugins)

    @property
    def remaining_full_slots(self) -> int:
        return max(0, FULL_SLOT_LIMIT - self.full_count)


def _subrecords(payload: bytes):
    pos = 0
    extended: int | None = None
    while pos + 6 <= len(payload):
        sig = payload[pos:pos + 4]
        size = struct.unpack_from("<H", payload, pos + 4)[0]
        pos += 6
        if sig == b"XXXX" and size == 4 and pos + 4 <= len(payload):
            extended = struct.unpack_from("<I", payload, pos)[0]
            pos += 4
            continue
        actual = extended if extended is not None else size
        extended = None
        if pos + actual > len(payload):
            break
        yield sig, payload[pos:pos + actual]
        pos += actual


def parse_plugin(path: Path) -> PluginInfo:
    info = PluginInfo(name=path.name, path=path)
    try:
        data = path.read_bytes()
        if len(data) < 24 or data[:4] != b"TES4":
            raise ValueError("not a valid TES4 plugin")
        header_size = struct.unpack_from("<I", data, 4)[0]
        info.flags = struct.unpack_from("<I", data, 8)[0]
        payload_end = 24 + header_size
        if payload_end > len(data):
            raise ValueError("truncated TES4 header")
        for sig, value in _subrecords(data[24:payload_end]):
            if sig == b"MAST":
                info.masters.append(value.rstrip(b"\0").decode("utf-8", errors="replace"))

        info.has_vmad = b"VMAD" in data
        stem = path.with_suffix("")
        archive_names = [path.with_suffix(".bsa"), Path(str(stem) + " - Textures.bsa")]
        info.has_archive = any(p.exists() for p in archive_names)

        def walk(start: int, end: int, depth: int = 0) -> None:
            pos = start
            while pos < end:
                if pos + 24 > end or pos + 24 > len(data):
                    raise ValueError("truncated record header")
                sig = data[pos:pos + 4]
                size = struct.unpack_from("<I", data, pos + 4)[0]
                if sig == b"GRUP":
                    if size < 24 or pos + size > end or pos + size > len(data):
                        raise ValueError("invalid group size")
                    if depth != 0 or struct.unpack_from("<I", data, pos + 12)[0] != 0:
                        info.flat_groups = False
                    group_end = pos + size
                    walk(pos + 24, group_end, depth + 1)
                    pos += size
                else:
                    total = 24 + size
                    if pos + total > end or pos + total > len(data):
                        raise ValueError("invalid record size")
                    if depth != 1:
                        info.flat_groups = False
                    try:
                        label = sig.decode("ascii")
                    except UnicodeDecodeError:
                        label = "????"
                    info.records[label] += 1
                    info.form_ids.append(struct.unpack_from("<I", data, pos + 12)[0])
                    pos += total

        walk(payload_end, len(data))
    except (OSError, ValueError, struct.error) as exc:
        info.error = str(exc)
    return info


def assess_load_order(data_dir: Path, active_names: list[str]) -> LoadOrderReport:
    plugins: list[PluginInfo] = []
    missing: list[str] = []
    for name in active_names:
        path = data_dir / name
        if path.is_file():
            plugins.append(parse_plugin(path))
        else:
            missing.append(name)

    reverse: dict[str, list[str]] = defaultdict(list)
    for plugin in plugins:
        for master in plugin.masters:
            reverse[master.casefold()].append(plugin.name)
    for plugin in plugins:
        plugin.depended_on_by = reverse.get(plugin.name.casefold(), [])

    builtin_full = [name for name in BUILTIN_FULL_PLUGINS if (data_dir / name).is_file() and name.casefold() not in {n.casefold() for n in active_names}]
    assessments: list[PluginAssessment] = []
    for plugin in plugins:
        reasons: list[str] = []
        protected = bool(PROTECTED_FRAMEWORK.search(plugin.name))
        if protected:
            reasons.append("Protected XP32/XPMSE skeleton framework: excluded from automatic merging and ESL flagging")
        risky = sorted(RISKY_RECORDS.intersection(plugin.records))
        if plugin.error:
            reasons.append(f"Could not parse: {plugin.error}")
        if plugin.is_master:
            reasons.append("Master plugin")
        if plugin.is_light:
            reasons.append("Already uses the light-plugin space")
        if plugin.depended_on_by:
            sample = ", ".join(plugin.depended_on_by[:3])
            more = "…" if len(plugin.depended_on_by) > 3 else ""
            reasons.append(f"Required by active plugin(s): {sample}{more}")
        if plugin.has_archive:
            reasons.append("Has an associated BSA archive")
        if plugin.has_vmad:
            reasons.append("Contains VMAD script data")
        if risky:
            reasons.append("Contains high-risk records: " + ", ".join(risky))
        if plugin.record_count > 1000:
            reasons.append(f"Large plugin ({plugin.record_count:,} records)")
        if not plugin.flat_groups:
            reasons.append("Uses nested or unusual record groups")
        if plugin.new_record_count:
            reasons.append(f"Creates {plugin.new_record_count:,} new records")
        unsupported = sorted(set(plugin.records).difference(MERGE_RECORDS))
        if unsupported:
            reasons.append("Contains record types outside the guarded merge set: " + ", ".join(unsupported[:8]))

        merge_ready = not reasons and plugin.record_count > 0
        missing_masters = [m for m in plugin.masters if not (data_dir / m).is_file()]
        esl_blockers = protected or plugin.error or plugin.is_master or plugin.is_light
        esl_review = not esl_blockers and plugin.record_count > 0
        # Pure overrides retain their masters' IDs. Nested groups, BSA loading,
        # dependents and record type are merge concerns, not reasons to compact.
        # Scripted plugins still require review for external ID assumptions.
        esl_ready = bool(esl_review and not plugin.new_record_count
                         and not plugin.has_vmad and not missing_masters)
        if missing_masters:
            reasons.append('Missing master files: ' + ', '.join(missing_masters))
        if plugin.is_light:
            esl_status = 'already_light'
        elif esl_ready:
            esl_status = 'flag_directly'
        elif esl_review:
            esl_status = 'manual_review' if plugin.esl_compatible_ids else 'needs_compaction_review'
        else:
            esl_status = 'protected_or_blocked'
        if esl_review and not plugin.esl_compatible_ids:
            reasons.append("New FormIDs exceed the light-plugin range; xEdit compaction would change them")
        if merge_ready:
            reasons.append("Override-only, flat records, and no active dependents")
        assessments.append(PluginAssessment(plugin, merge_ready, esl_review, reasons, merge_ready, esl_ready, esl_status))
    return LoadOrderReport(plugins, assessments, missing, builtin_full)
