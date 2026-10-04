# Sparky ⚡

Sparky is a Windows desktop companion for Skyrim Special Edition and Vortex. It finds ways to reclaim full plugin slots, creates guarded Vortex-installable merge and ESL overlay archives, and translates Trainwreck crash logs into plain English.

## Start

Run the uploaded `Sparky-0.6.exe` at the repository root, or double-click `run_sparky.bat`. Local builds can also be launched from `dist/Sparky-0.6.exe`. From source, run `python -m sparky.gui` with Python 3.10 or newer.

Version 0.6 evaluates pure overrides independently of merge restrictions: associated BSAs, dependent plugins, nested groups, and record types no longer disqualify a flag-only copy. Missing masters and detected VMAD script data prevent automatic flagging; new records require review. XP32 remains protected. See [xEdit's patch flagging guidance](https://tes5edit.github.io/docs/8-managing-mod-files.html#8104---adding-the-esl-flag-for-mod-users). Eligibility is not in-game validation.

Version 0.5 separates ESL record eligibility from merge eligibility, adding override-only CLFM, IDLE, and NPC_ plugins to the existing guarded flagging checks. The ESL tab shows ready, manual-review, compaction-review, and blocked categories. Review candidates cannot be flagged automatically; framework protections remain in place. This is structural eligibility, not in-game validation of individual mods.

Version 0.4 adds **Flag selected plugin now** in ESL Flagging. Close Skyrim, scan, select an eligible ESP, and click the button. It saves the original in `backups/`, applies the flag to the deployed plugin, verifies the bytes, and refreshes eligibility. Atomic file replacement preserves any Vortex staging hardlink source. Vortex redeployment may undo this direct change; the overlay ZIP remains the Vortex-managed option. Restore a backup under the original plugin filename to undo direct flagging.

Version 0.3 gives ESL flagging its own **ESL Flagging** tab. XP32/XPMSE/XPMSSE filenames (including named patches) are excluded from both automatic builders, with a visible reason. This name-based safeguard cannot identify arbitrary renamed framework plugins.

On the Dashboard, confirm the four detected paths. Use **Browse** if Skyrim, Vortex, or your crash logs are elsewhere. Press **Scan active load order**. The Build tab then lists eligible plugins. Output ZIPs appear in `exports/` beside the app (inside `dist/exports/` for the packaged EXE); use Vortex's **Install From File** on the chosen ZIP.

## What the builders do

**Guarded merge:** Combines two or more active, override-only, flat-group patches when they have precisely the same master list. It rejects new records, scripts, archives, nested groups, high-risk record types, and plugins needed by another active plugin. Where source plugins override the same record, the one later in the current load order wins. The archive contains a new ESP and installation instructions. Keep source mods installed for loose assets, but disable the source ESPs after installing the merge. Use SSEEdit to inspect the result and a new test save before trusting it.

**ESL overlay:** Copies an eligible override-only ESP and changes only its ESL header flag. It retains the original filename and FormIDs. Install the ZIP with Vortex and let it win the file conflict over the original plugin. The original mod remains installed for its assets. Disable the overlay in Vortex to undo it.

The ZIP builders do not edit live Data files. Direct flagging explicitly edits the selected deployed plugin. Neither action edits Vortex staging, `plugins.txt`, or saves. Actions are opt-in through the UI.

The merge rules are intentionally narrow. A plugin that Sparky rejects may still be mergeable in zMerge after expert review. A plugin listed for **ESL review** but absent from the automatic ESL list may need FormID compaction; that changes IDs and can break existing saves, dependent mods, FaceGen, and voice files. Sparky does not compact FormIDs automatically.

## Crash translator

Select the latest Trainwreck log or browse for one. Sparky highlights concrete evidence such as asset paths and stack components, gives a confidence level, and looks for the implicated asset in the Vortex staging folder. These findings are diagnostic leads, not proof of blame.

## Command line

```powershell
python -m sparky.cli scan
python -m sparky.cli crash
python -m sparky.cli crash "C:\path\to\crash.log"
```

## Development

Sparky uses the Python standard library at runtime.

```powershell
python -m unittest discover -s tests -v
```

To package a Windows executable, install PyInstaller in your build environment and run:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Sparky-0.6 launcher.py
```

The repository includes `launcher.py` for packaging.

## Source references

- [xEdit: managing mod files and ESL risks](https://tes5edit.github.io/docs/8-managing-mod-files.html)
- [xEdit: zMerge recommendation](https://tes5edit.github.io/docs/14-Scripting-Resources.html)
- [zEdit/zMerge project](https://github.com/z-edit/zedit)
