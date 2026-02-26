import tkinter as tk
from tkinter import ttk, filedialog
import os
from datetime import datetime
import threading

from core.settings import AppSettings, SettingsManager
from core.service import ImportService, MonitorService

class MainWindow(tk.Tk):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.title("Bandcamp LinkFilter")
        self.geometry("650x550")
        self.minsize(600, 500)
        
        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        
        self.service_thread = None
        self.current_service = None
        
        self._build_ui()
        self._load_settings_to_ui()

    def _build_ui(self):
        # --- File Selection Frame ---
        file_frame = ttk.LabelFrame(self, text="File Paths", padding=10)
        file_frame.pack(fill="x", padx=10, pady=5)
        
        # Log File
        ttk.Label(file_frame, text="Log File:").grid(row=0, column=0, sticky="e", pady=2)
        self.entry_log_file = ttk.Entry(file_frame, width=50)
        self.entry_log_file.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(file_frame, text="Browse...", command=self._browse_log_file).grid(row=0, column=2, pady=2)
        
        # Output Folder
        ttk.Label(file_frame, text="Output Folder:").grid(row=1, column=0, sticky="e", pady=2)
        self.entry_out_folder = ttk.Entry(file_frame, width=50)
        self.entry_out_folder.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        ttk.Button(file_frame, text="Browse...", command=self._browse_out_folder).grid(row=1, column=2, pady=2)
        
        file_frame.columnconfigure(1, weight=1)

        # --- Options Frame ---
        options_frame = ttk.LabelFrame(self, text="Options & Filters", padding=10)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # Mode
        mode_frame = ttk.Frame(options_frame)
        mode_frame.grid(row=0, column=0, columnspan=4, sticky="w", pady=5)
        ttk.Label(mode_frame, text="Mode:").pack(side="left")
        self.var_mode = tk.StringVar(value="import")
        ttk.Radiobutton(mode_frame, text="Import", variable=self.var_mode, value="import").pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="Monitor", variable=self.var_mode, value="monitor").pack(side="left", padx=5)
        
        # Checkboxes & Gen Options
        self.var_append_desc = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Append description", variable=self.var_append_desc).grid(row=1, column=0, sticky="w", pady=2)
        
        self.var_avoid_dup = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Avoid duplicates", variable=self.var_avoid_dup).grid(row=2, column=0, sticky="w", pady=2)
        
        # Numeric Filters
        ttk.Label(options_frame, text="Min tracks:").grid(row=1, column=1, sticky="e", padx=5, pady=2)
        self.entry_min_tracks = ttk.Entry(options_frame, width=10)
        self.entry_min_tracks.grid(row=1, column=2, sticky="w", pady=2)
        
        ttk.Label(options_frame, text="Min duration (min):").grid(row=2, column=1, sticky="e", padx=5, pady=2)
        self.entry_min_duration = ttk.Entry(options_frame, width=10)
        self.entry_min_duration.grid(row=2, column=2, sticky="w", pady=2)

        # Export Naming & Timestamp Logic
        ttk.Label(options_frame, text="Filename:").grid(row=3, column=0, sticky="w", pady=2)
        self.entry_custom_filename = ttk.Entry(options_frame, width=20)
        self.entry_custom_filename.grid(row=3, column=1, sticky="w", pady=2)
        
        self.var_add_filter_info = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Add filter info to filename", variable=self.var_add_filter_info).grid(row=3, column=2, sticky="w", pady=2)

        self.var_filter_timestamp = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="Filter by Timestamp", variable=self.var_filter_timestamp).grid(row=4, column=0, sticky="w", pady=2)
        
        ttk.Label(options_frame, text="Last TS:").grid(row=4, column=1, sticky="e", padx=5, pady=2)
        self.entry_last_timestamp = ttk.Entry(options_frame, width=25)
        self.entry_last_timestamp.grid(row=4, column=2, sticky="w", pady=2)

        # --- Action Buttons ---
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill="x", padx=10)
        
        self.btn_start = ttk.Button(btn_frame, text="Start", command=self._start)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ttk.Button(btn_frame, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.btn_dry_run = ttk.Button(btn_frame, text="Search / Dry Run", command=self._dry_run)
        self.btn_dry_run.pack(side="left", padx=5)

        # --- Statistics ---
        stats_frame = ttk.Frame(self, padding=0)
        stats_frame.pack(fill="x", padx=15)
        
        self.lbl_total_imported = ttk.Label(stats_frame, text="Total Imported: 0")
        self.lbl_total_imported.pack(side="left", padx=5)
        
        self.lbl_ready_export = ttk.Label(stats_frame, text="Ready for Export: 0")
        self.lbl_ready_export.pack(side="left", padx=20)

        # --- Status ---
        status_frame = ttk.LabelFrame(self, text="Status", padding=10)
        status_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.lbl_status = ttk.Label(status_frame, text="Ready.", wraplength=550)
        self.lbl_status.pack(anchor="nw", fill="both", expand=True)

    def _browse_log_file(self):
        filename = filedialog.askopenfilename(title="Select Log File")
        if filename:
            self.entry_log_file.delete(0, tk.END)
            self.entry_log_file.insert(0, filename)

    def _browse_out_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.entry_out_folder.delete(0, tk.END)
            self.entry_out_folder.insert(0, folder)

    def _update_status(self, msg: str):
        # We might receive piped messages like: 
        # "Import complete...|2026-02-16T...Z"
        # or "Dry Run Complete|10|5"
        def _apply():
            if msg.startswith("Dry Run Complete"):
                parts = msg.split('|')
                self.lbl_status.config(text=parts[0])
                if len(parts) >= 3:
                    self.lbl_total_imported.config(text=f"Total Imported: {parts[1]}")
                    self.lbl_ready_export.config(text=f"Ready for Export: {parts[2]}")
            else:
                parts = msg.split('|')
                self.lbl_status.config(text=parts[0])
                if len(parts) > 1 and parts[1]: # This is max_timestamp
                    ts = parts[1]
                    self.settings.last_export_timestamp = ts
                    self.entry_last_timestamp.delete(0, tk.END)
                    self.entry_last_timestamp.insert(0, ts)
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
        if self.settings.min_duration is not None:
            self.entry_min_duration.insert(0, str(self.settings.min_duration))

        self.entry_custom_filename.insert(0, self.settings.custom_filename)
        self.var_add_filter_info.set(self.settings.add_filter_info)
        self.var_filter_timestamp.set(self.settings.filter_by_timestamp)
        self.entry_last_timestamp.insert(0, self.settings.last_export_timestamp)

    def _save_settings_from_ui(self):
        self.settings.log_file_path = self.entry_log_file.get().strip()
        self.settings.output_folder_path = self.entry_out_folder.get().strip()
        self.settings.mode = self.var_mode.get()
        self.settings.append_description = self.var_append_desc.get()
        self.settings.avoid_duplicates = self.var_avoid_dup.get()
        self.settings.custom_filename = self.entry_custom_filename.get().strip()
        self.settings.add_filter_info = self.var_add_filter_info.get()
        self.settings.filter_by_timestamp = self.var_filter_timestamp.get()
        self.settings.last_export_timestamp = self.entry_last_timestamp.get().strip()
        
        # Parse ints safely
        try:
            val = self.entry_min_tracks.get().strip()
            self.settings.min_tracks = int(val) if val else None
        except ValueError:
            self.settings.min_tracks = None
            
        try:
            val = self.entry_min_duration.get().strip()
            self.settings.min_duration = int(val) if val else None
        except ValueError:
            self.settings.min_duration = None

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
            if self.settings.min_tracks is not None:
                suffix += f"_T{self.settings.min_tracks}"
            if self.settings.min_duration is not None:
                suffix += f"_M{self.settings.min_duration}"
            base_name += suffix
        
        if not base_name.endswith(".txt"):
            base_name += ".txt"
            
        out_file = os.path.join(out_folder, base_name)

        # Disable UI
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_dry_run.config(state="disabled")
        
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
            
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.btn_dry_run.config(state="disabled")
        
        self.lbl_total_imported.config(text="Total Imported: ...")
        self.lbl_ready_export.config(text="Ready for Export: ...")
        
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
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_dry_run.config(state="normal")
        self.current_service = None

    def _stop(self):
        if self.current_service:
            self.current_service.stop()
            self._update_status("Stopping...")
            self.btn_stop.config(state="disabled")
