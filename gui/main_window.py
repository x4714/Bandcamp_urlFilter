import tkinter as tk
from tkinter import ttk, filedialog
import os
from datetime import datetime
import re
import threading

def format_timestamp_for_ui(ts: str) -> str:
    """Converts '2026-02-16T12:00:00Z' to '16.02.2026 12:00' for display."""
    if not ts:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", ts)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}:{m.group(5)}"
    return ts

def parse_timestamp_from_ui(ts: str) -> str:
    """Converts user input back to ISO format 'YYYY-MM-DDTHH:MM:SSZ'."""
    ts = ts.strip()
    if not ts:
        return ""
    if "T" in ts and ts.endswith("Z"):
        return ts
    
    formats = [
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return ts


from core.settings import AppSettings, SettingsManager
from core.service import ImportService, MonitorService

class MainWindow(ctk.CTk):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.title("Bandcamp LinkFilter")
        self.geometry("650x550")
        self.minsize(600, 500)
        
        self.service_thread = None
        self.current_service = None
        
        self._build_ui()
        self._load_settings_to_ui()

    def _build_ui(self):
        # --- File Selection Frame ---
        file_frame = ctk.CTkFrame(self)
        file_frame.pack(fill="x", padx=10, pady=5)
        
        # Log File
        ctk.CTkLabel(file_frame, text="Log File:").grid(row=0, column=0, sticky="e", pady=5, padx=5)
        self.entry_log_file = ctk.CTkEntry(file_frame, width=300)
        self.entry_log_file.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(file_frame, text="Browse...", command=self._browse_log_file).grid(row=0, column=2, pady=5, padx=5)
        
        # Output Folder
        ctk.CTkLabel(file_frame, text="Output Folder:").grid(row=1, column=0, sticky="e", pady=5, padx=5)
        self.entry_out_folder = ctk.CTkEntry(file_frame, width=300)
        self.entry_out_folder.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkButton(file_frame, text="Browse...", command=self._browse_out_folder).grid(row=1, column=2, pady=5, padx=5)
        
        file_frame.columnconfigure(1, weight=1)

        # --- Options Frame ---
        options_frame = ctk.CTkFrame(self)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # Mode
        mode_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        mode_frame.grid(row=0, column=0, columnspan=4, sticky="w", pady=5, padx=5)
        ctk.CTkLabel(mode_frame, text="Mode:").pack(side="left", padx=(0, 10))
        self.var_mode = ctk.StringVar(value="import")
        ctk.CTkRadioButton(mode_frame, text="Import", variable=self.var_mode, value="import").pack(side="left", padx=5)
        ctk.CTkRadioButton(mode_frame, text="Monitor", variable=self.var_mode, value="monitor").pack(side="left", padx=5)
        
        # Checkboxes & Gen Options
        self.var_append_desc = ctk.BooleanVar()
        ctk.CTkCheckBox(options_frame, text="Append description", variable=self.var_append_desc).grid(row=1, column=0, sticky="w", pady=5, padx=5)
        
        self.var_avoid_dup = ctk.BooleanVar()
        ctk.CTkCheckBox(options_frame, text="Avoid duplicates", variable=self.var_avoid_dup).grid(row=2, column=0, sticky="w", pady=5, padx=5)
        
        # Numeric Filters
        ctk.CTkLabel(options_frame, text="Min tracks:").grid(row=1, column=1, sticky="e", padx=5, pady=5)
        self.entry_min_tracks = ctk.CTkEntry(options_frame, width=80)
        self.entry_min_tracks.grid(row=1, column=2, sticky="w", pady=5)

        ctk.CTkLabel(options_frame, text="Max tracks:").grid(row=1, column=3, sticky="e", padx=5, pady=5)
        self.entry_max_tracks = ctk.CTkEntry(options_frame, width=80)
        self.entry_max_tracks.grid(row=1, column=4, sticky="w", pady=5)
        
        ctk.CTkLabel(options_frame, text="Min duration (min):").grid(row=2, column=1, sticky="e", padx=5, pady=5)
        self.entry_min_duration = ctk.CTkEntry(options_frame, width=80)
        self.entry_min_duration.grid(row=2, column=2, sticky="w", pady=5)

        ctk.CTkLabel(options_frame, text="Max duration (min):").grid(row=2, column=3, sticky="e", padx=5, pady=5)
        self.entry_max_duration = ctk.CTkEntry(options_frame, width=80)
        self.entry_max_duration.grid(row=2, column=4, sticky="w", pady=5)

        # Export Naming & Timestamp Logic
        ctk.CTkLabel(options_frame, text="Filename:").grid(row=3, column=0, sticky="w", pady=5, padx=5)
        self.entry_custom_filename = ctk.CTkEntry(options_frame, width=150)
        self.entry_custom_filename.grid(row=3, column=1, columnspan=2, sticky="w", pady=5)
        
        self.var_add_filter_info = ctk.BooleanVar()
        ctk.CTkCheckBox(options_frame, text="Add filter info to filename", variable=self.var_add_filter_info).grid(row=3, column=2, columnspan=2, sticky="w", pady=5, padx=5)

        self.var_filter_timestamp = ctk.BooleanVar()
        ctk.CTkCheckBox(options_frame, text="Filter by Timestamp", variable=self.var_filter_timestamp).grid(row=4, column=0, sticky="w", pady=5, padx=5)
        
        ctk.CTkLabel(options_frame, text="Last TS (DD.MM.YYYY (HH:MM)):").grid(row=4, column=1, sticky="e", padx=5, pady=5)
        self.entry_last_timestamp = ctk.CTkEntry(options_frame, width=200)
        self.entry_last_timestamp.grid(row=4, column=2, columnspan=2, sticky="w", pady=5)

        # --- Action Buttons ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        self.btn_start = ctk.CTkButton(btn_frame, text="Start", command=self._start)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ctk.CTkButton(btn_frame, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.btn_dry_run = ctk.CTkButton(btn_frame, text="Search / Dry Run", command=self._dry_run)
        self.btn_dry_run.pack(side="left", padx=5)

        # --- Statistics ---
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.pack(fill="x", padx=15, pady=5)
        
        self.lbl_total_imported = ctk.CTkLabel(stats_frame, text="Total Imported: 0")
        self.lbl_total_imported.pack(side="left", padx=5)
        
        self.lbl_ready_export = ctk.CTkLabel(stats_frame, text="Ready for Export: 0")
        self.lbl_ready_export.pack(side="left", padx=20)

        # --- Status ---
        status_frame = ctk.CTkFrame(self)
        status_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.lbl_status = ctk.CTkLabel(status_frame, text="Ready.", wraplength=550, anchor="nw", justify="left")
        self.lbl_status.pack(anchor="nw", fill="both", expand=True, padx=10, pady=10)

    def _browse_log_file(self):
        filename = filedialog.askopenfilename(title="Select Log File")
        if filename:
            self.entry_log_file.delete(0, 'end')
            self.entry_log_file.insert(0, filename)

    def _browse_out_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.entry_out_folder.delete(0, 'end')
            self.entry_out_folder.insert(0, folder)

    def _update_status(self, msg: str):
        # We might receive piped messages like: 
        # "Import complete...|2026-02-16T...Z"
        # or "Dry Run Complete|10|5"
        def _apply():
            if msg.startswith("Dry Run Complete"):
                parts = msg.split('|')
                self.lbl_status.configure(text=parts[0])
                if len(parts) >= 3:
                    self.lbl_total_imported.configure(text=f"Total Imported: {parts[1]}")
                    self.lbl_ready_export.configure(text=f"Ready for Export: {parts[2]}")
            else:
                parts = msg.split('|')
                self.lbl_status.configure(text=parts[0])
                if len(parts) > 1 and parts[1]: # This is max_timestamp
                    ts = parts[1]
                    self.settings.last_export_timestamp = ts
                    self.entry_last_timestamp.delete(0, 'end')
                    self.entry_last_timestamp.insert(0, format_timestamp_for_ui(ts))
                    SettingsManager.save(self.settings)
        
        self.after(0, _apply)

    def _load_settings_to_ui(self):
        self.entry_log_file.insert(0, self.settings.log_file_path)
        self.entry_out_folder.insert(0, self.settings.output_folder_path)
        self.var_mode.set(self.settings.mode if self.settings.mode in ["import", "monitor"] else "import")
        self.var_append_desc.set(self.settings.append_description)
        self.var_avoid_dup.set(self.settings.avoid_duplicates)
        
        if self.settings.min_tracks is not None:
            self.entry_min_tracks.insert(0, str(self.settings.min_tracks))
        if self.settings.max_tracks is not None:
            self.entry_max_tracks.insert(0, str(self.settings.max_tracks))
        if self.settings.min_duration is not None:
            self.entry_min_duration.insert(0, str(self.settings.min_duration))
        if self.settings.max_duration is not None:
            self.entry_max_duration.insert(0, str(self.settings.max_duration))

        self.entry_custom_filename.insert(0, self.settings.custom_filename)
        self.var_add_filter_info.set(self.settings.add_filter_info)
        self.var_filter_timestamp.set(self.settings.filter_by_timestamp)
        self.entry_last_timestamp.insert(0, format_timestamp_for_ui(self.settings.last_export_timestamp))

    def _save_settings_from_ui(self):
        self.settings.log_file_path = self.entry_log_file.get().strip()
        self.settings.output_folder_path = self.entry_out_folder.get().strip()
        self.settings.mode = self.var_mode.get()
        self.settings.append_description = self.var_append_desc.get()
        self.settings.avoid_duplicates = self.var_avoid_dup.get()
        self.settings.custom_filename = self.entry_custom_filename.get().strip()
        self.settings.add_filter_info = self.var_add_filter_info.get()
        self.settings.filter_by_timestamp = self.var_filter_timestamp.get()
        self.settings.last_export_timestamp = parse_timestamp_from_ui(self.entry_last_timestamp.get().strip())
        
        # Parse ints safely
        try:
            val = self.entry_min_tracks.get().strip()
            self.settings.min_tracks = int(val) if val else None
        except ValueError:
            self.settings.min_tracks = None

        try:
            val = self.entry_max_tracks.get().strip()
            self.settings.max_tracks = int(val) if val else None
        except ValueError:
            self.settings.max_tracks = None
            
        try:
            val = self.entry_min_duration.get().strip()
            self.settings.min_duration = int(val) if val else None
        except ValueError:
            self.settings.min_duration = None

        try:
            val = self.entry_max_duration.get().strip()
            self.settings.max_duration = int(val) if val else None
        except ValueError:
            self.settings.max_duration = None

        SettingsManager.save(self.settings)

    def _start(self):
        self._save_settings_from_ui()
        
        in_path = self.settings.log_file_path
        out_folder = self.settings.output_folder_path
        
        if not in_path or not os.path.exists(in_path):
            self._update_status(f"Error: Invalid log file path: {in_path}")
            return
            
        if not out_folder or not os.path.isdir(out_folder):
            self._update_status(f"Error: Invalid output folder path: {out_folder}")
            return

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_name = self.settings.custom_filename if self.settings.custom_filename else f"export_{ts}"
        if self.settings.add_filter_info:
            suffix = ""
            if self.settings.min_tracks is not None or self.settings.max_tracks is not None:
                min_t = self.settings.min_tracks if self.settings.min_tracks is not None else ""
                max_t = self.settings.max_tracks if self.settings.max_tracks is not None else ""
                suffix += f"_T{min_t}-{max_t}"
            if self.settings.min_duration is not None or self.settings.max_duration is not None:
                min_d = self.settings.min_duration if self.settings.min_duration is not None else ""
                max_d = self.settings.max_duration if self.settings.max_duration is not None else ""
                suffix += f"_M{min_d}-{max_d}"
            base_name += suffix
        
        if not base_name.endswith(".txt"):
            base_name += ".txt"
            
        out_file = os.path.join(out_folder, base_name)

        # Disable UI
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_dry_run.configure(state="disabled")
        
        # Decide service
        if self.settings.mode == "import":
            self.current_service = ImportService(self.settings, self._update_status)
        else:
            self.current_service = MonitorService(self.settings, self._update_status)

        # Run in thread so GUI doesn't freeze
        self.service_thread = threading.Thread(target=self._run_service, args=(in_path, out_file), daemon=True)
        self.service_thread.start()

    def _dry_run(self):
        self._save_settings_from_ui()
        in_path = self.settings.log_file_path
        
        if not in_path or not os.path.exists(in_path):
            self._update_status(f"Error: Invalid log file path: {in_path}")
            return
            
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_dry_run.configure(state="disabled")
        
        self.lbl_total_imported.configure(text="Total Imported: ...")
        self.lbl_ready_export.configure(text="Ready for Export: ...")
        
        self.current_service = ImportService(self.settings, self._update_status)
        out_folder = self.settings.output_folder_path
        dummy_out_file = os.path.join(out_folder, "dummy.txt") if out_folder else ""
        
        self.service_thread = threading.Thread(target=self._run_dry_run_service, args=(in_path, dummy_out_file), daemon=True)
        self.service_thread.start()

    def _run_dry_run_service(self, in_path: str, out_file: str):
        try:
            self.current_service.dry_run(in_path, out_file)
        finally:
            self.after(0, self._on_service_complete)

    def _run_service(self, in_path: str, out_file: str):
        try:
            self.current_service.run(in_path, out_file)
        finally:
            self.after(0, self._on_service_complete)
            
    def _on_service_complete(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_dry_run.configure(state="normal")
        self.current_service = None

    def _stop(self):
        if self.current_service:
            self.current_service.stop()
            self._update_status("Stopping...")
            self.btn_stop.configure(state="disabled")
