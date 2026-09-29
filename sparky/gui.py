from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .builder import build_esl_overlay, build_merge, flag_esl_now
from .cli import render_load_order
from .crash import analyze_crash, render_crash_report
from .paths import SkyrimPaths, read_active_plugins
from .plugins import assess_load_order


class SparkyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sparky 0.6 — Skyrim Safety Assistant")
        self.geometry("1020x720")
        self.minsize(800, 560)
        self.app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        self.settings_file = self.app_dir / "settings.json"
        self.paths = SkyrimPaths.from_settings(self.settings_file)
        self.events: queue.Queue = queue.Queue()
        self.load_report = None
        self.export_dir = self.app_dir / "exports"
        self._style()
        self._build()
        self.after(100, self._drain_events)

    def _style(self):
        self.configure(bg="#111827")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#e5e7eb", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground="#fbbf24")
        style.configure("Safe.TLabel", foreground="#86efac")
        style.configure("TButton", padding=9, font=("Segoe UI Semibold", 10))
        style.configure("TNotebook", background="#111827")
        style.configure("TNotebook.Tab", padding=(14, 8))

    def _build(self):
        top = ttk.Frame(self, padding=16)
        top.pack(fill="x")
        ttk.Label(top, text="⚡ Sparky", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, text="Plugin space, guarded builds, and Trainwreck translation", style="Safe.TLabel").pack(anchor="w")
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.home = ttk.Frame(tabs, padding=18)
        self.plugins_tab = ttk.Frame(tabs, padding=18)
        self.build_tab = ttk.Frame(tabs, padding=18)
        self.esl_tab = ttk.Frame(tabs, padding=18)
        self.crash_tab = ttk.Frame(tabs, padding=18)
        tabs.add(self.home, text="Dashboard")
        tabs.add(self.plugins_tab, text="Plugin Space")
        tabs.add(self.build_tab, text="Build")
        tabs.add(self.esl_tab, text="ESL Flagging")
        tabs.add(self.crash_tab, text="Crash Translator")

        ttk.Label(self.home, text="Detected Skyrim setup", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        self.path_labels = {}
        for label, field_name, is_file in (
            ("Game Data", "data", False), ("Active plugins", "plugins_txt", True),
            ("Crash logs", "crashlogs", False), ("Vortex staging", "vortex_mods", False),
        ):
            row = ttk.Frame(self.home)
            row.pack(fill="x", pady=2)
            widget = ttk.Label(row, text=f"{label}: {getattr(self.paths, field_name)}", wraplength=820)
            widget.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Browse…", command=lambda key=field_name, file=is_file: self.choose_path(key, file)).pack(side="right")
            self.path_labels[field_name] = (label, widget)
        ttk.Label(self.home, text="ZIP builds leave game files untouched. Flag selected plugin now edits the deployed plugin and saves a backup.", style="Safe.TLabel", wraplength=900).pack(anchor="w", pady=(18, 8))
        ttk.Button(self.home, text="Scan active load order", command=self.scan_plugins).pack(anchor="w", pady=4)
        ttk.Button(self.home, text="Translate latest crash", command=self.latest_crash).pack(anchor="w", pady=4)

        self.plugin_status = ttk.Label(self.plugins_tab, text="Press Scan to inspect plugin headers.")
        self.plugin_status.pack(anchor="w")
        ttk.Button(self.plugins_tab, text="Scan", command=self.scan_plugins).pack(anchor="w", pady=8)
        self.plugin_text = self._text(self.plugins_tab)

        ttk.Label(self.build_tab, text="Automatic guarded merge", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(self.build_tab, text="Select two or more compatible override-only patches. Later load-order edits win on overlapping records.", wraplength=900).pack(anchor="w", pady=(3, 8))
        self.merge_list = tk.Listbox(self.build_tab, selectmode="extended", height=7, bg="#0b1220", fg="#e5e7eb", selectbackground="#92400e", font=("Consolas", 10))
        self.merge_list.pack(fill="x")
        merge_controls = ttk.Frame(self.build_tab)
        merge_controls.pack(fill="x", pady=8)
        ttk.Label(merge_controls, text="Merged plugin name:").pack(side="left")
        self.merge_name = ttk.Entry(merge_controls, width=32)
        self.merge_name.insert(0, "SparkyMergedPatches.esp")
        self.merge_name.pack(side="left", padx=8)
        ttk.Button(merge_controls, text="Build merge ZIP", command=self.build_merge).pack(side="left")

        ttk.Label(self.esl_tab, text="ESL flagging — no FormID compaction", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(self.esl_tab, text="Select an eligible override-only ESP and flag it now, or build an overlay ZIP. Direct flagging backs up and replaces the deployed plugin; Vortex redeployment may undo it. Close Skyrim before flagging. Filename and FormIDs stay unchanged. Protected frameworks are excluded.", wraplength=900).pack(anchor="w", pady=(3, 8))
        ttk.Button(self.esl_tab, text="Scan eligible plugins", command=self.scan_plugins).pack(anchor="w", pady=8)
        self.esl_list = tk.Listbox(self.esl_tab, height=10, bg="#0b1220", fg="#e5e7eb", selectbackground="#92400e", font=("Consolas", 10))
        self.esl_list.pack(fill="x")
        ttk.Button(self.esl_tab, text="Flag selected plugin now", command=self.flag_esl).pack(anchor="w", pady=8)
        ttk.Button(self.esl_tab, text="Build ESL overlay ZIP", command=self.build_esl).pack(anchor="w", pady=8)
        self.esl_status = ttk.Label(self.esl_tab, text="Scan to find eligible plugins.", wraplength=900)
        self.esl_status.pack(anchor="w")
        self.esl_text = self._text(self.esl_tab)
        self.build_status = ttk.Label(self.build_tab, text="Scan the load order to populate eligible plugins.", style="Safe.TLabel", wraplength=900)
        self.build_status.pack(anchor="w", pady=(4, 8))
        self.build_text = self._text(self.build_tab)

        crash_buttons = ttk.Frame(self.crash_tab)
        crash_buttons.pack(fill="x")
        ttk.Button(crash_buttons, text="Latest Trainwreck log", command=self.latest_crash).pack(side="left", padx=(0, 8))
        ttk.Button(crash_buttons, text="Choose log…", command=self.choose_crash).pack(side="left")
        self.crash_status = ttk.Label(self.crash_tab, text="No log analyzed yet.")
        self.crash_status.pack(anchor="w", pady=8)
        self.crash_text = self._text(self.crash_tab)

    @staticmethod
    def _text(parent):
        widget = tk.Text(parent, wrap="word", bg="#0b1220", fg="#e5e7eb", insertbackground="white", relief="flat", padx=12, pady=12, font=("Consolas", 10))
        widget.pack(fill="both", expand=True)
        return widget

    def _work(self, message, fn):
        def runner():
            try:
                self.events.put(("ok", fn()))
            except Exception as exc:  # GUI boundary
                self.events.put(("error", str(exc)))
        self.plugin_status.configure(text=message)
        self.crash_status.configure(text=message)
        threading.Thread(target=runner, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "error":
                    messagebox.showerror("Sparky", payload)
                    self.plugin_status.configure(text="Analysis failed.")
                    self.crash_status.configure(text="Analysis failed.")
                    self.esl_status.configure(text="Operation failed; see the error message.")
                else:
                    target, text, status, *extra = payload
                    target.delete("1.0", "end")
                    target.insert("1.0", text)
                    self.plugin_status.configure(text=status)
                    self.crash_status.configure(text=status)
                    self.build_status.configure(text=status)
                    self.esl_status.configure(text=status)
                    if extra:
                        self._populate_build(extra[0])
                        if target is self.esl_text:
                            self.esl_text.insert('1.0', text + '\n\n')
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def scan_plugins(self):
        def run():
            report = assess_load_order(self.paths.data, read_active_plugins(self.paths.plugins_txt))
            status = f"Complete: {report.full_count} full, {report.light_count} light, {report.remaining_full_slots} full slots remaining."
            return self.plugin_text, render_load_order(report), status, report
        self._work("Reading active plugin headers…", run)

    def _populate_build(self, report):
        self.load_report = report
        self.merge_list.delete(0, "end")
        self.esl_list.delete(0, "end")
        compatible = {}
        for item in report.assessments:
            if item.merge_ready:
                compatible.setdefault(tuple(m.casefold() for m in item.plugin.masters), []).append(item.plugin.name)
        merge_names = {name for group in compatible.values() if len(group) >= 2 for name in group}
        for item in report.assessments:
            if item.plugin.name in merge_names:
                self.merge_list.insert("end", item.plugin.name)
            if item.esl_ready:
                self.esl_list.insert("end", item.plugin.name)
        self.build_status.configure(text=f"{self.merge_list.size()} plugins in compatible merge groups; {self.esl_list.size()} automatic ESL overlays. Exports: {self.export_dir}")
        self.esl_status.configure(text=f"{self.esl_list.size()} eligible plugins. See Plugin Space for exclusions and manual-review candidates.")
        self.esl_text.delete('1.0', 'end')
        sections = [('flag_directly', 'READY TO FLAG'), ('manual_review', 'MANUAL REVIEW — IDs fit; other checks remain'), ('needs_compaction_review', 'COMPACTION REVIEW — not automatic'), ('protected_or_blocked', 'PROTECTED / BLOCKED')]
        lines = []
        for category, title in sections:
            items = [a for a in report.assessments if a.esl_status == category]
            lines.append(f'{title} ({len(items)})')
            for item in items:
                detail = 'No FormID changes needed' if item.esl_ready else '; '.join(item.reasons)
                lines.append(f'  {item.plugin.name}: {detail}')
            lines.append('')
        self.esl_text.insert('1.0', '\n'.join(lines))

    def choose_path(self, field_name: str, is_file: bool):
        current = getattr(self.paths, field_name)
        selected = filedialog.askopenfilename(initialdir=current.parent, filetypes=[("Plugin list", "*.txt"), ("All files", "*.*")]) if is_file else filedialog.askdirectory(initialdir=current)
        if not selected:
            return
        self.paths = replace(self.paths, **{field_name: Path(selected)})
        label, widget = self.path_labels[field_name]
        widget.configure(text=f"{label}: {selected}")
        try:
            self.paths.save_settings(self.settings_file)
        except OSError as exc:
            messagebox.showwarning("Sparky", f"Path works for this session but could not be saved: {exc}")
        self.load_report = None
        self.merge_list.delete(0, "end")
        self.esl_list.delete(0, "end")
        self.build_status.configure(text="Paths changed. Scan the load order again.")
        self.esl_status.configure(text="Paths changed. Scan the load order again.")

    def build_merge(self):
        selected = [self.merge_list.get(index) for index in self.merge_list.curselection()]
        name = self.merge_name.get().strip()
        if len(selected) < 2:
            messagebox.showinfo("Sparky", "Select at least two merge candidates.")
            return
        def run():
            path = build_merge(self.paths.data, read_active_plugins(self.paths.plugins_txt), selected, name, self.export_dir)
            return self.build_text, f"Created: {path}\n\nInstall the ZIP in Vortex. Keep the source mods installed for loose assets; disable only the source ESPs after enabling the merge. Check the merged plugin in SSEEdit and test on a new save.", f"Built {path.name}"
        self._work("Validating and building merge…", run)

    def build_esl(self):
        selection = self.esl_list.curselection()
        if not selection:
            messagebox.showinfo("Sparky", "Select one ESL candidate.")
            return
        selected = self.esl_list.get(selection[0])
        def run():
            path = build_esl_overlay(self.paths.data, read_active_plugins(self.paths.plugins_txt), selected, self.export_dir)
            return self.esl_text, f"Created: {path}\n\nInstall the ZIP in Vortex and let it win the plugin file conflict. Deploy, verify the plugin is light, and test on a new save. Disable the overlay to undo.", f"Built {path.name}"
        self._work("Validating and building ESL overlay…", run)

    def flag_esl(self):
        selection = self.esl_list.curselection()
        if not selection:
            messagebox.showinfo('Sparky', 'Select one ESL candidate.')
            return
        selected = self.esl_list.get(selection[0])
        def run():
            active = read_active_plugins(self.paths.plugins_txt)
            backup = flag_esl_now(self.paths.data, active, selected, self.app_dir / 'backups')
            report = assess_load_order(self.paths.data, active)
            return self.esl_text, f'ESL flag applied and verified: {selected}\nBackup: {backup}\n\nVortex redeployment may restore the original. Use the overlay ZIP option for a Vortex-managed change. To undo, close Skyrim and copy the backup over the deployed plugin using its original filename.', f'Flagged {selected}', report
        self._work('Backing up and applying ESL flag…', run)

    def latest_crash(self):
        path = self.paths.latest_crash()
        if not path:
            messagebox.showinfo("Sparky", "No Trainwreck log was found.")
            return
        self._analyze_crash(path)

    def choose_crash(self):
        selected = filedialog.askopenfilename(initialdir=self.paths.crashlogs, filetypes=[("Crash logs", "*.log"), ("All files", "*.*")])
        if selected:
            from pathlib import Path
            self._analyze_crash(Path(selected))

    def _analyze_crash(self, path):
        def run():
            report = analyze_crash(path, self.paths.vortex_mods, read_active_plugins(self.paths.plugins_txt))
            confidence = report.findings[0].confidence if report.findings else "Low"
            return self.crash_text, render_crash_report(report), f"Analyzed {path.name} — top finding: {confidence} confidence."
        self._work("Reading crash evidence and checking Vortex providers…", run)


def main():
    SparkyApp().mainloop()


if __name__ == "__main__":
    main()
