"""
Multi-Drive Formatter
=====================
Opens a GUI file/drive selector and formats all selected external drives at once.

SUPPORTED PLATFORMS: Windows, macOS, Linux
WARNING: This will permanently erase all data on selected drives. Use with caution.
"""

import os
import sys
import platform
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import string

# ──────────────────────────────────────────────
# PLATFORM DETECTION
# ──────────────────────────────────────────────
OS = platform.system()  # 'Windows', 'Darwin', 'Linux'


# ──────────────────────────────────────────────
# DRIVE DETECTION
# ──────────────────────────────────────────────

def get_removable_drives():
    """Return a list of dicts: {label, path, size} for removable/external drives."""
    drives = []

    if OS == "Windows":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                path = f"{letter}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(path)
                # 2 = DRIVE_REMOVABLE, 3 = DRIVE_FIXED (some USB HDDs show as fixed)
                if drive_type in (2, 3) and letter not in ("C",):
                    try:
                        total, _, _ = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
                        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                            path,
                            ctypes.byref(ctypes.c_ulonglong()),
                            ctypes.byref(total),
                            ctypes.byref(ctypes.c_ulonglong()),
                        )
                        size_gb = total.value / (1024 ** 3)
                        vol_name = ctypes.create_unicode_buffer(261)
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            path, vol_name, 261, None, None, None, None, 0
                        )
                        label = vol_name.value or f"Drive {letter}:"
                        drives.append({"label": label, "path": path, "size": f"{size_gb:.1f} GB", "type": "Removable" if drive_type == 2 else "USB HDD"})
                    except Exception:
                        drives.append({"label": f"Drive {letter}:", "path": path, "size": "Unknown", "type": "External"})
            bitmask >>= 1

    elif OS == "Darwin":  # macOS
        result = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True, text=True
        )
        import plistlib
        try:
            plist = plistlib.loads(result.stdout.encode())
            for disk in plist.get("AllDisksAndPartitions", []):
                disk_id = disk.get("DeviceIdentifier", "")
                info = subprocess.run(
                    ["diskutil", "info", "-plist", f"/dev/{disk_id}"],
                    capture_output=True, text=True
                )
                disk_info = plistlib.loads(info.stdout.encode())
                mount = disk_info.get("MountPoint", "")
                size_bytes = disk_info.get("TotalSize", 0)
                size_gb = size_bytes / (1024 ** 3)
                name = disk_info.get("VolumeName") or disk_info.get("MediaName") or disk_id
                if mount:
                    drives.append({"label": name, "path": mount, "size": f"{size_gb:.1f} GB", "type": "External"})
        except Exception as e:
            pass

    else:  # Linux
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,MOUNTPOINT,RM,VENDOR,LABEL,TYPE"],
            capture_output=True, text=True
        )
        import json
        try:
            data = json.loads(result.stdout)
            for device in data.get("blockdevices", []):
                # RM=1 means removable
                if device.get("rm") == "1" or device.get("rm") is True:
                    for child in device.get("children", [device]):
                        mp = child.get("mountpoint")
                        if mp and mp not in ("/", "/boot"):
                            label = child.get("label") or child.get("name")
                            drives.append({
                                "label": label,
                                "path": mp,
                                "size": child.get("size", "?"),
                                "type": "Removable",
                                "dev": f"/dev/{child['name']}"
                            })
        except Exception:
            pass

    return drives


# ──────────────────────────────────────────────
# FORMAT LOGIC (per OS)
# ──────────────────────────────────────────────

def format_drive(drive, fs_type, log_callback):
    """Format a single drive. Calls log_callback(msg) for status updates."""
    path = drive["path"]
    label = drive["label"]

    log_callback(f"[{label}] Starting format ({fs_type})...")

    try:
        if OS == "Windows":
            letter = path[0].upper()

            # ── Method 1: PowerShell Format-Volume (most reliable on Win10/11) ──
            ps_fs = {"exFAT": "exFAT", "FAT32": "FAT32", "NTFS": "NTFS"}.get(fs_type, "exFAT")
            ps_cmd = (
                f"Format-Volume -DriveLetter {letter} "
                f"-FileSystem {ps_fs} -NewFileSystemLabel '{label}' "
                f"-Force -Confirm:$false"
            )
            log_callback(f"[{label}] Trying PowerShell Format-Volume...")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=180
            )

            if result.returncode == 0 and "successfully" not in result.stderr.lower():
                log_callback(f"[{label}] ✅ Format complete.")
            else:
                # ── Method 2: diskpart script as fallback ──
                log_callback(f"[{label}] PowerShell failed, trying diskpart...")
                fs_diskpart = {"exFAT": "exFAT", "FAT32": "FAT32", "NTFS": "NTFS"}.get(fs_type, "exFAT")
                script = (
                    f"select volume {letter}\n"
                    f"format fs={fs_diskpart} quick\n"
                    "exit\n"
                )
                script_path = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "diskpart_fmt.txt")
                with open(script_path, "w") as f:
                    f.write(script)

                dp_result = subprocess.run(
                    ["diskpart", "/s", script_path],
                    capture_output=True, text=True, timeout=180
                )
                os.remove(script_path)

                out = dp_result.stdout + dp_result.stderr
                if dp_result.returncode == 0 and "successfully" in out.lower():
                    log_callback(f"[{label}] ✅ Format complete.")
                else:
                    log_callback(f"[{label}] ❌ Error (diskpart): {out.strip()[:300]}")
                    log_callback(f"[{label}] 💡 Make sure you ran as Administrator.")

        elif OS == "Darwin":
            # diskutil eraseVolume <fs> <name> <mountpoint>
            fs_map = {"FAT32": "FAT32", "exFAT": "ExFAT", "APFS": "APFS", "HFS+": "HFS+"}
            dk_fs = fs_map.get(fs_type, "ExFAT")
            cmd = ["diskutil", "eraseVolume", dk_fs, label, path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                log_callback(f"[{label}] ✅ Format complete.")
            else:
                log_callback(f"[{label}] ❌ Error: {result.stderr}")

        else:  # Linux
            dev = drive.get("dev", path)
            fs_map = {"FAT32": "vfat", "exFAT": "exfat", "ext4": "ext4", "NTFS": "ntfs"}
            mk_fs = fs_map.get(fs_type, "vfat")
            # Unmount first
            subprocess.run(["umount", dev], capture_output=True)
            cmd = ["mkfs." + mk_fs, "-F", dev] if mk_fs == "vfat" else ["mkfs." + mk_fs, dev]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                log_callback(f"[{label}] ✅ Format complete.")
            else:
                log_callback(f"[{label}] ❌ Error: {result.stderr}")

    except subprocess.TimeoutExpired:
        log_callback(f"[{label}] ❌ Timed out.")
    except Exception as e:
        log_callback(f"[{label}] ❌ Exception: {e}")


# ──────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────

class FormatterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Multi-Drive Formatter")
        self.geometry("680x560")
        self.resizable(True, True)
        self.configure(bg="#1a1a2e")

        self.drives = []
        self.check_vars = []

        self._build_ui()
        self._refresh_drives()

    # ── UI Construction ──────────────────────
    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCheckbutton", background="#16213e", foreground="#e0e0e0",
                        font=("Consolas", 10))
        style.configure("TButton", background="#0f3460", foreground="white",
                        font=("Consolas", 10, "bold"), padding=6)
        style.map("TButton", background=[("active", "#e94560")])
        style.configure("Danger.TButton", background="#e94560", foreground="white",
                        font=("Consolas", 11, "bold"), padding=8)
        style.map("Danger.TButton", background=[("active", "#c0392b")])
        style.configure("TCombobox", fieldbackground="#16213e", background="#16213e",
                        foreground="#e0e0e0", font=("Consolas", 10))

        # Title
        tk.Label(self, text="⚡ MULTI-DRIVE FORMATTER", bg="#1a1a2e", fg="#e94560",
                 font=("Consolas", 16, "bold")).pack(pady=(18, 2))
        tk.Label(self, text="Select external drives to format simultaneously",
                 bg="#1a1a2e", fg="#8892b0", font=("Consolas", 9)).pack(pady=(0, 12))

        # Drive List Frame
        frame = tk.Frame(self, bg="#16213e", bd=1, relief="solid")
        frame.pack(fill="both", expand=False, padx=20, pady=4)

        tk.Label(frame, text="DETECTED DRIVES", bg="#16213e", fg="#64ffda",
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 4))

        self.drive_frame = tk.Frame(frame, bg="#16213e")
        self.drive_frame.pack(fill="x", padx=10, pady=(0, 10))

        # Refresh button
        btn_row = tk.Frame(self, bg="#1a1a2e")
        btn_row.pack(fill="x", padx=20, pady=6)
        ttk.Button(btn_row, text="🔄  Refresh Drives", command=self._refresh_drives).pack(side="left")
        ttk.Button(btn_row, text="✅  Select All", command=self._select_all).pack(side="left", padx=8)
        ttk.Button(btn_row, text="⬜  Deselect All", command=self._deselect_all).pack(side="left")

        # Format options
        opts_frame = tk.Frame(self, bg="#16213e", bd=1, relief="solid")
        opts_frame.pack(fill="x", padx=20, pady=8)
        tk.Label(opts_frame, text="FORMAT OPTIONS", bg="#16213e", fg="#64ffda",
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 4))

        row = tk.Frame(opts_frame, bg="#16213e")
        row.pack(fill="x", padx=10, pady=(0, 10))

        tk.Label(row, text="Filesystem:", bg="#16213e", fg="#e0e0e0",
                 font=("Consolas", 10)).pack(side="left")

        fs_options = {
            "Windows": ["exFAT", "FAT32", "NTFS"],
            "Darwin":  ["exFAT", "FAT32", "APFS", "HFS+"],
            "Linux":   ["FAT32", "exFAT", "ext4", "NTFS"],
        }.get(OS, ["exFAT", "FAT32"])

        self.fs_var = tk.StringVar(value=fs_options[0])
        ttk.Combobox(row, textvariable=self.fs_var, values=fs_options,
                     state="readonly", width=12).pack(side="left", padx=12)

        tk.Label(row, text="(exFAT recommended for memory cards)",
                 bg="#16213e", fg="#8892b0", font=("Consolas", 8)).pack(side="left")

        # Log
        log_frame = tk.Frame(self, bg="#1a1a2e")
        log_frame.pack(fill="both", expand=True, padx=20, pady=(4, 0))
        tk.Label(log_frame, text="LOG", bg="#1a1a2e", fg="#64ffda",
                 font=("Consolas", 9, "bold")).pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=8, bg="#0d0d1a", fg="#a8ff78",
                                font=("Consolas", 9), state="disabled", bd=0)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Format Button
        ttk.Button(self, text="🗑️  FORMAT SELECTED DRIVES",
                   style="Danger.TButton", command=self._confirm_format).pack(pady=14)

    # ── Drive Refresh ────────────────────────
    def _refresh_drives(self):
        for widget in self.drive_frame.winfo_children():
            widget.destroy()
        self.check_vars.clear()

        self.drives = get_removable_drives()

        if not self.drives:
            tk.Label(self.drive_frame, text="  No external drives detected. Insert a memory card and click Refresh.",
                     bg="#16213e", fg="#8892b0", font=("Consolas", 9)).pack(anchor="w", pady=6)
            return

        for drive in self.drives:
            var = tk.BooleanVar(value=False)
            self.check_vars.append(var)
            row = tk.Frame(self.drive_frame, bg="#16213e")
            row.pack(fill="x", pady=2)
            ttk.Checkbutton(row, variable=var,
                            text=f"  {drive['label']}   [{drive['path']}]   {drive['size']}   ({drive['type']})"
                            ).pack(side="left")

    def _select_all(self):
        for v in self.check_vars:
            v.set(True)

    def _deselect_all(self):
        for v in self.check_vars:
            v.set(False)

    # ── Logging ──────────────────────────────
    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ── Confirm & Format ─────────────────────
    def _confirm_format(self):
        selected = [self.drives[i] for i, v in enumerate(self.check_vars) if v.get()]
        if not selected:
            messagebox.showwarning("No Selection", "Please select at least one drive.")
            return

        names = "\n".join(f"  • {d['label']} ({d['path']}) — {d['size']}" for d in selected)
        confirm = messagebox.askyesno(
            "⚠️ CONFIRM FORMAT",
            f"This will PERMANENTLY ERASE all data on:\n\n{names}\n\n"
            f"Filesystem: {self.fs_var.get()}\n\nAre you absolutely sure?",
            icon="warning"
        )
        if not confirm:
            self._log("Format cancelled by user.")
            return

        fs = self.fs_var.get()
        self._log(f"Starting format of {len(selected)} drive(s) as {fs}...")

        def run():
            threads = []
            for drive in selected:
                t = threading.Thread(
                    target=format_drive,
                    args=(drive, fs, lambda msg: self.after(0, self._log, msg)),
                    daemon=True
                )
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
            self.after(0, self._log, "─── All done. ───")
            self.after(0, self._refresh_drives)

        threading.Thread(target=run, daemon=True).start()


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if OS == "Linux" and os.geteuid() != 0:
        print("⚠️  On Linux, formatting requires root. Re-run with: sudo python format_drives.py")
    elif OS == "Windows":
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("⚠️  On Windows, formatting requires Administrator. Right-click and 'Run as Administrator'.")

    app = FormatterApp()
    app.mainloop()