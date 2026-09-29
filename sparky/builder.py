"""Guarded builders. Outputs are Vortex-installable archives outside the game."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
import re
import struct
import zipfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from .plugins import TES4_LIGHT, assess_load_order, parse_plugin


class BuildError(ValueError):
    pass


def flag_esl_now(data_dir: Path, active_names: list[str], selected: str, backup_dir: Path) -> Path:
    """Flag a deployed plugin using atomic replacement, preserving Vortex hardlink sources."""
    if selected not in active_names or Path(selected).name != selected:
        raise BuildError("Select an active plugin filename")
    source = data_dir / selected
    original = source.read_bytes()
    report = assess_load_order(data_dir, active_names)
    assessment = next((a for a in report.assessments if a.plugin.name == selected), None)
    if not assessment or not assessment.esl_ready:
        raise BuildError(f"{selected} is not eligible for automatic ESL flagging")
    changed = bytearray(original)
    struct.pack_into('<I', changed, 8, struct.unpack_from('<I', original, 8)[0] | TES4_LIGHT)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f'{source.stem}-{uuid.uuid4().hex}.esp.bak'
    with backup.open('xb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=data_dir, suffix='.esp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(changed)
            stream.flush()
            os.fsync(stream.fileno())
        verified = parse_plugin(temporary)
        if verified.error or not verified.is_light or verified.form_ids != assessment.plugin.form_ids:
            raise BuildError('Flagged plugin failed verification; original was not changed')
        if source.read_bytes() != original:
            raise BuildError('Plugin changed during validation; original was not replaced')
        os.replace(temporary, source)
        temporary = None
        if source.read_bytes() != bytes(changed):
            raise BuildError(f'Post-write verification failed. Backup: {backup}')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def _safe_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}\.esp", name, re.IGNORECASE):
        raise BuildError("Use a simple .esp filename with letters, numbers, spaces, dots, hyphens, or underscores.")
    return name


def _header_and_groups(data: bytes):
    if len(data) < 24 or data[:4] != b"TES4":
        raise BuildError("Invalid TES4 plugin")
    header_end = 24 + struct.unpack_from("<I", data, 4)[0]
    if header_end > len(data):
        raise BuildError("Truncated TES4 header")
    groups: OrderedDict[bytes, list[bytes]] = OrderedDict()
    group_headers: dict[bytes, bytes] = {}
    pos = header_end
    while pos < len(data):
        if data[pos:pos + 4] != b"GRUP" or pos + 24 > len(data):
            raise BuildError("Only flat top-level groups can be merged")
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if size < 24 or pos + size > len(data) or struct.unpack_from("<I", data, pos + 12)[0] != 0:
            raise BuildError("Invalid or nested group")
        label = data[pos + 8:pos + 12]
        group_headers.setdefault(label, data[pos:pos + 24])
        records = groups.setdefault(label, [])
        child = pos + 24
        while child < pos + size:
            if child + 24 > pos + size or data[child:child + 4] == b"GRUP":
                raise BuildError("Nested or truncated group")
            rec_size = 24 + struct.unpack_from("<I", data, child + 4)[0]
            if child + rec_size > pos + size:
                raise BuildError("Truncated record")
            record = data[child:child + rec_size]
            if record[:4] != label:
                raise BuildError("Record type does not match its group")
            records.append(record)
            child += rec_size
        pos += size
    return data[:header_end], groups, group_headers


def _update_header_count(header: bytes, count: int) -> bytes:
    result = bytearray(header)
    pos = 24
    while pos + 6 <= len(result):
        sig = result[pos:pos + 4]
        size = struct.unpack_from("<H", result, pos + 4)[0]
        if sig == b"HEDR" and size >= 12:
            struct.pack_into("<I", result, pos + 10, count)
            return bytes(result)
        pos += 6 + size
    raise BuildError("TES4 header has no HEDR record count")


def _archive(path: Path, plugin_name: str, plugin_bytes: bytes, notes: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(plugin_name, plugin_bytes)
        archive.writestr("Sparky installation.txt", notes)
    return path


def build_merge(data_dir: Path, active_names: list[str], selected: list[str], output_name: str, export_dir: Path) -> Path:
    output_name = _safe_name(output_name)
    if len(selected) < 2 or len({n.casefold() for n in selected}) != len(selected):
        raise BuildError("Select at least two different plugins")
    report = assess_load_order(data_dir, active_names)
    by_name = {a.plugin.name.casefold(): a for a in report.assessments}
    ordered = sorted(selected, key=lambda n: next((i for i, x in enumerate(active_names) if x.casefold() == n.casefold()), 10**9))
    if output_name.casefold() in {n.casefold() for n in active_names}:
        raise BuildError("The merged filename already exists in the active load order")
    sources = []
    for name in ordered:
        item = by_name.get(name.casefold())
        if item is None or not item.merge_ready:
            raise BuildError(f"{name} is not eligible for the guarded merge: " + ("; ".join(item.reasons) if item else "not active"))
        sources.append(item.plugin)
    masters = [m.casefold() for m in sources[0].masters]
    if any([m.casefold() for m in source.masters] != masters for source in sources[1:]):
        raise BuildError("Selected plugins must have exactly the same masters in the same order")

    header: bytes | None = None
    merged: OrderedDict[bytes, OrderedDict[int, bytes]] = OrderedDict()
    group_headers: dict[bytes, bytes] = {}
    for source in sources:
        data = source.path.read_bytes()
        fresh = parse_plugin(source.path)
        if (fresh.error or fresh.new_record_count or not fresh.flat_groups or fresh.has_vmad
                or fresh.flags != source.flags or fresh.masters != source.masters
                or fresh.records != source.records or fresh.has_archive != source.has_archive):
            raise BuildError(f"{source.name} changed or failed validation")
        this_header, groups, this_group_headers = _header_and_groups(data)
        if header is None:
            header = this_header
        for label, records in groups.items():
            group_headers.setdefault(label, this_group_headers[label])
            target = merged.setdefault(label, OrderedDict())
            for record in records:
                form_id = struct.unpack_from("<I", record, 12)[0]
                if form_id >> 24 >= len(masters):
                    raise BuildError(f"{source.name} contains a locally owned record")
                target[form_id] = record  # later load order wins
    if header is None:
        raise BuildError("No records to merge")
    count = sum(len(group) for group in merged.values())
    output = bytearray(_update_header_count(header, count))
    for label, records in merged.items():
        content = b"".join(records.values())
        group_header = bytearray(group_headers[label])
        struct.pack_into("<I", group_header, 4, 24 + len(content))
        output.extend(group_header)
        output.extend(content)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(output).hexdigest()[:12]
    destination = export_dir / f"Sparky-Merge-{Path(output_name).stem}-{stamp}-{digest}.zip"
    notes = (
        "Sparky guarded merge\n\n"
        f"Merged plugin: {output_name}\nSources in load order: {', '.join(ordered)}\n"
        f"Masters: {', '.join(sources[0].masters)}\nRecords: {count}\nSHA-256: {hashlib.sha256(output).hexdigest()}\n\n"
        "Install this archive with Vortex. Keep the source mods installed so their loose assets remain available. "
        "Disable only the source ESP plugins in Vortex, enable the merged ESP, deploy, and start a new test save. "
        "Verify the result in SSEEdit before using an existing save. Re-enable the source ESPs and disable the merge to undo.\n"
    )
    _archive(destination, output_name, bytes(output), notes)
    built = parse_plugin_from_archive(destination, output_name)
    if built.error or built.record_count != count or [m.casefold() for m in built.masters] != masters:
        destination.unlink(missing_ok=True)
        raise BuildError("Built plugin failed structural verification")
    return destination


def parse_plugin_from_archive(archive_path: Path, plugin_name: str):
    # Validation uses a temporary file so the ordinary parser checks the complete output.
    import tempfile
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / plugin_name
        path.write_bytes(archive.read(plugin_name))
        return parse_plugin(path)


def build_esl_overlay(data_dir: Path, active_names: list[str], selected: str, export_dir: Path) -> Path:
    report = assess_load_order(data_dir, active_names)
    assessment = next((a for a in report.assessments if a.plugin.name.casefold() == selected.casefold()), None)
    if not assessment or not assessment.esl_ready:
        raise BuildError(f"{selected} is not eligible for automatic ESL flagging")
    source = assessment.plugin
    data = bytearray(source.path.read_bytes())
    struct.pack_into("<I", data, 8, source.flags | TES4_LIGHT)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = export_dir / f"Sparky-ESL-{source.path.stem}-{stamp}.zip"
    notes = (
        f"Sparky ESL overlay for {source.name}\n\n"
        "Install in Vortex and set this mod to win the file conflict over the original plugin. "
        "Keep the original mod installed for its assets. Deploy and verify the plugin is light in Vortex/SSEEdit. "
        "Use a new test save first. Disable this overlay to undo.\n"
    )
    _archive(destination, source.name, bytes(data), notes)
    built = parse_plugin_from_archive(destination, source.name)
    if built.error or not built.is_light or built.record_count != source.record_count:
        destination.unlink(missing_ok=True)
        raise BuildError("ESL overlay failed structural verification")
    return destination
