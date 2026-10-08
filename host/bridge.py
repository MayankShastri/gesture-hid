"""
Gesture Bridge — Host-side Python Application
Connects to ESP8266 + MPU6050 over USB-Serial, classifies foreground
application context on Windows, and executes mapped macro shortcuts.
"""

import threading
import time
import ctypes
from collections import deque
import serial
import serial.tools.list_ports
import customtkinter as ctk

try:
    import win32gui
    import win32process
    import psutil
except ImportError:
    win32gui = None
    win32process = None
    psutil = None

# ---------------------------------------------------------------------------
# Direct Windows Hardware Scan Code Input via user32.keybd_event & mouse_event
# (Ensures 100% reliable Alt+Tab, Volume OSD, Smooth Browser Scrolling)
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32

VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22   # Page Down
VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12   # Alt key
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

# Scan codes
SCAN_ALT = 0x38
SCAN_TAB = 0x0F
SCAN_LEFT = 0x4B
SCAN_RIGHT = 0x4D
SCAN_UP = 0x48
SCAN_DOWN = 0x50

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_WHEEL = 0x0800

def press_key(vk, scan=0, extended=False):
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    user32.keybd_event(vk, scan, flags, 0)
    time.sleep(0.015)
    user32.keybd_event(vk, scan, flags | KEYEVENTF_KEYUP, 0)

def hotkey(vk1, scan1, vk2, scan2, extended1=False, extended2=False):
    flags1 = KEYEVENTF_EXTENDEDKEY if extended1 else 0
    flags2 = KEYEVENTF_EXTENDEDKEY if extended2 else 0
    user32.keybd_event(vk1, scan1, flags1, 0)
    time.sleep(0.015)
    user32.keybd_event(vk2, scan2, flags2, 0)
    time.sleep(0.015)
    user32.keybd_event(vk2, scan2, flags2 | KEYEVENTF_KEYUP, 0)
    time.sleep(0.01)
    user32.keybd_event(vk1, scan1, flags1 | KEYEVENTF_KEYUP, 0)

def scroll(clicks):
    # clicks > 0 is scroll up, clicks < 0 is scroll down (gentle step)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(clicks * 50), 0)

COMBO_WINDOW_S = 0.90
BAUD = 9600

# ---------------------------------------------------------------------------
# App profiles with high-visibility actions
# ---------------------------------------------------------------------------
PROFILES = {
    "browser": {
        "match": ["chrome", "msedge", "edge", "firefox", "brave", "opera", "arc", "vivaldi", "browser"],
        "SWIPE_LEFT":        ("Browser Back (Alt+←)", lambda: hotkey(VK_MENU, SCAN_ALT, VK_LEFT, SCAN_LEFT, extended2=True)),
        "SWIPE_RIGHT":       ("Browser Forward (Alt+→)", lambda: hotkey(VK_MENU, SCAN_ALT, VK_RIGHT, SCAN_RIGHT, extended2=True)),
        "SWIPE_UP":          ("Fast Scroll Down", lambda: scroll(-2)),
        "SWIPE_DOWN":        ("Fast Scroll Up", lambda: scroll(2)),
        "TILT_HOLD_LEFT":    ("Previous Tab (Ctrl+Shift+Tab)", lambda: hotkey(VK_CONTROL, 0x1D, VK_PRIOR, 0x49, extended2=True)),
        "TILT_HOLD_RIGHT":   ("Next Tab (Ctrl+Tab)", lambda: hotkey(VK_CONTROL, 0x1D, VK_NEXT, 0x51, extended2=True)),
        "TILT_HOLD_FORWARD": ("Scroll Down", lambda: scroll(-1)),
        "TILT_HOLD_BACKWARD":("Scroll Up", lambda: scroll(1)),
    },
    "media": {
        "match": ["spotify", "vlc", "wmplayer", "groove", "itunes", "music", "tidal", "media"],
        "SWIPE_LEFT":        ("Previous Track", lambda: press_key(VK_MEDIA_PREV_TRACK, extended=True)),
        "SWIPE_RIGHT":       ("Next Track", lambda: press_key(VK_MEDIA_NEXT_TRACK, extended=True)),
        "SWIPE_UP":          ("Play / Pause", lambda: press_key(VK_MEDIA_PLAY_PAUSE, extended=True)),
        "SWIPE_DOWN":        ("Mute / Unmute", lambda: press_key(VK_VOLUME_MUTE, extended=True)),
        "TILT_HOLD_LEFT":    ("Previous Track", lambda: press_key(VK_MEDIA_PREV_TRACK, extended=True)),
        "TILT_HOLD_RIGHT":   ("Next Track", lambda: press_key(VK_MEDIA_NEXT_TRACK, extended=True)),
        "TILT_HOLD_FORWARD": ("Volume Up", lambda: press_key(VK_VOLUME_UP, extended=True)),
        "TILT_HOLD_BACKWARD":("Volume Down", lambda: press_key(VK_VOLUME_DOWN, extended=True)),
    },
    "photos": {
        "match": ["photos", "picture", "gallery", "image", "viewer", "paint", "photoviewer"],
        "SWIPE_LEFT":        ("Previous Photo (←)", lambda: press_key(VK_LEFT, SCAN_LEFT, extended=True)),
        "SWIPE_RIGHT":       ("Next Photo (→)", lambda: press_key(VK_RIGHT, SCAN_RIGHT, extended=True)),
        "SWIPE_UP":          ("Zoom In (↑)", lambda: press_key(VK_UP, SCAN_UP, extended=True)),
        "SWIPE_DOWN":        ("Zoom Out (↓)", lambda: press_key(VK_DOWN, SCAN_DOWN, extended=True)),
        "TILT_HOLD_LEFT":    ("Hold Prev Photo (←)", lambda: press_key(VK_LEFT, SCAN_LEFT, extended=True)),
        "TILT_HOLD_RIGHT":   ("Hold Next Photo (→)", lambda: press_key(VK_RIGHT, SCAN_RIGHT, extended=True)),
        "TILT_HOLD_FORWARD": ("Hold Zoom In (↑)", lambda: press_key(VK_UP, SCAN_UP, extended=True)),
        "TILT_HOLD_BACKWARD":("Hold Zoom Out (↓)", lambda: press_key(VK_DOWN, SCAN_DOWN, extended=True)),
    },
    "default": {
        "match": [],
        "SWIPE_LEFT":        ("Arrow Left (←)", lambda: press_key(VK_LEFT, SCAN_LEFT, extended=True)),
        "SWIPE_RIGHT":       ("Arrow Right (→)", lambda: press_key(VK_RIGHT, SCAN_RIGHT, extended=True)),
        "SWIPE_UP":          ("Page Up (Scroll)", lambda: scroll(2)),
        "SWIPE_DOWN":        ("Page Down (Scroll)", lambda: scroll(-2)),
        "TILT_HOLD_LEFT":    ("Hold Left (←)", lambda: press_key(VK_LEFT, SCAN_LEFT, extended=True)),
        "TILT_HOLD_RIGHT":   ("Hold Right (→)", lambda: press_key(VK_RIGHT, SCAN_RIGHT, extended=True)),
        "TILT_HOLD_FORWARD": ("Scroll Down", lambda: scroll(-1)),
        "TILT_HOLD_BACKWARD":("Scroll Up", lambda: scroll(1)),
    },
}


def get_foreground_app():
    if win32gui is None:
        return "unknown"
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "unknown"
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        name = ""
        if psutil is not None and pid > 0:
            try:
                name = psutil.Process(pid).name().lower()
            except Exception:
                name = ""
        return f"{name} | {title}".strip(" |")
    except Exception:
        return "unknown"


def resolve_profile(app_str):
    s = (app_str or "").lower()
    for name, profile in PROFILES.items():
        if name == "default":
            continue
        for token in profile["match"]:
            if token in s:
                return name
    return "default"


def find_serial_port():
    ports = list(serial.tools.list_ports.comports())
    keywords = ("cp210", "ch340", "ch341", "silicon labs", "usb-serial", "uart")
    for p in ports:
        desc = f"{p.description} {p.manufacturer or ''}".lower()
        if any(k in desc for k in keywords):
            return p.device
    if ports:
        return ports[-1].device
    return None


class GestureBridge:
    def __init__(self, on_event):
        self.on_event = on_event
        self.ser = None
        self.running = False
        self.last_flick_time = 0.0
        self.last_flick_label = None
        self.combo_active = False
        self.alt_held = False
        self.last_tilt_event_time = 0.0
        self.log = deque(maxlen=80)

    def connect(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0.2)
        time.sleep(0.3)

    def send_command(self, cmd):
        if self.ser and self.ser.is_open:
            self.ser.write(f"{cmd.strip()}\n".encode("utf-8"))

    def close(self):
        self.running = False
        self._release_alt()
        if self.ser and self.ser.is_open:
            self.ser.close()

    def start(self):
        self.running = True
        t = threading.Thread(target=self._read_loop, daemon=True)
        t.start()
        w = threading.Thread(target=self._watchdog_loop, daemon=True)
        w.start()

    def _watchdog_loop(self):
        while self.running:
            time.sleep(0.05)
            if self.alt_held or self.combo_active:
                # If no tilt packet received within 400ms, release Alt
                if (time.time() - self.last_tilt_event_time) > 0.45:
                    self._release_alt()
                    app = get_foreground_app()
                    self.on_event("combo", {
                        "gesture": "COMBO_RELEASE (TIMEOUT)",
                        "profile": resolve_profile(app),
                        "app": app,
                        "macro": "Alt Released -> Switched Window!",
                    })

    def _read_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception as e:
                self.on_event("error", f"Serial error: {e}")
                break
            if line:
                self._handle(line)

    def _release_alt(self):
        if self.alt_held or self.combo_active:
            try:
                user32.keybd_event(VK_MENU, SCAN_ALT, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
            self.alt_held = False
            self.combo_active = False

    def _start_combo(self):
        self.combo_active = True
        self.last_tilt_event_time = time.time()
        if not self.alt_held:
            # Hold down Alt with physical scan code
            user32.keybd_event(VK_MENU, SCAN_ALT, 0, 0)
            self.alt_held = True
            time.sleep(0.03)
        # Pulse Tab
        user32.keybd_event(VK_TAB, SCAN_TAB, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_TAB, SCAN_TAB, KEYEVENTF_KEYUP, 0)

    def _cycle_combo(self):
        self.last_tilt_event_time = time.time()
        # Pulse Tab again while Alt is held
        user32.keybd_event(VK_TAB, SCAN_TAB, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_TAB, SCAN_TAB, KEYEVENTF_KEYUP, 0)

    def _handle(self, line):
        if line.startswith("TELEM:"):
            self.on_event("telem", line[6:])
            return

        now = time.time()
        app = get_foreground_app()
        profile_name = resolve_profile(app)
        profile = PROFILES[profile_name]

        if line.startswith("SWIPE_"):
            self.last_flick_time = now
            self.last_flick_label = line
            self._dispatch(line, profile, profile_name, app)
            return

        if line.startswith("TILT_HOLD_"):
            self.last_tilt_event_time = now
            # Check if flick happened recently -> trigger Alt+Tab Combo
            if (not self.combo_active
                    and self.last_flick_label
                    and (now - self.last_flick_time) <= COMBO_WINDOW_S):
                self._start_combo()
                self.on_event("combo", {
                    "gesture": "COMBO_START",
                    "profile": profile_name,
                    "app": app,
                    "macro": "Alt+Tab Switcher Opened",
                })
                return

            if self.combo_active:
                self._cycle_combo()
                self.on_event("combo", {
                    "gesture": "COMBO_HOLD",
                    "profile": profile_name,
                    "app": app,
                    "macro": "Cycling Next Window (Tab)",
                })
                return

            self._dispatch(line, profile, profile_name, app)
            return

        if line == "TILT_RELEASE":
            self.last_flick_label = None
            if self.combo_active or self.alt_held:
                self._release_alt()
                self.on_event("combo", {
                    "gesture": "COMBO_RELEASE",
                    "profile": profile_name,
                    "app": app,
                    "macro": "Alt Released -> Switched Window!",
                })
                return
            self.on_event("gesture", {
                "gesture": line,
                "profile": profile_name,
                "app": app,
                "macro": "(neutral level)",
            })
            return

        if line.startswith("STATUS:"):
            self.on_event("status", line)
            return

    def _dispatch(self, gesture, profile, profile_name, app):
        entry = profile.get(gesture)
        if entry:
            label, action = entry
            try:
                action()
                macro = label
            except Exception as e:
                self.on_event("error", f"Macro failed: {e}")
                return
        else:
            macro = "(unmapped)"
        self.on_event("gesture", {
            "gesture": gesture,
            "profile": profile_name,
            "app": app,
            "macro": macro,
        })


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Gesture Input Device — ESP8266 + MPU6050")
        self.geometry("860x640")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bridge = GestureBridge(self._on_event)
        self.connected = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkLabel(self, text="Gesture-Controlled Human Interface Device",
                              font=ctk.CTkFont(size=22, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")

        # Top controls
        top_frame = ctk.CTkFrame(self)
        top_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")

        ctk.CTkLabel(top_frame, text="Port:").pack(side="left", padx=(10, 4), pady=8)
        self.entry_port = ctk.CTkEntry(top_frame, width=110)
        default_port = find_serial_port() or "COM7"
        self.entry_port.insert(0, default_port)
        self.entry_port.pack(side="left", padx=4, pady=8)

        self.btn_connect = ctk.CTkButton(top_frame, text="Connect", width=85,
                                         command=self._toggle_connect)
        self.btn_connect.pack(side="left", padx=6, pady=8)

        self.btn_calibrate = ctk.CTkButton(top_frame, text="Calibrate / Center", width=120,
                                           fg_color="#d35400", hover_color="#e67e22",
                                           command=self._on_calibrate)
        self.btn_calibrate.pack(side="left", padx=6, pady=8)

        self.lbl_status = ctk.CTkLabel(top_frame, text="Status: Disconnected",
                                       text_color="gray")
        self.lbl_status.pack(side="right", padx=10, pady=8)

        # Dashboard cards
        status = ctk.CTkFrame(self)
        status.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        for i in range(6):
            status.grid_columnconfigure(i, weight=1)

        self.lbl_app = self._stat(status, 0, "Focused App", "—")
        self.lbl_profile = self._stat(status, 1, "Active Profile", "—")
        self.lbl_last_g = self._stat(status, 2, "Last Gesture", "—")
        self.lbl_macro = self._stat(status, 3, "Dispatched Action", "—")
        self.lbl_angles = self._stat(status, 4, "Roll / Pitch", "0° / 0°")
        self.lbl_gyro = self._stat(status, 5, "Gyro Rate", "0 / 0 / 0")

        # Quick guide banner
        guide = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1e1e1e"))
        guide.grid(row=3, column=0, padx=20, pady=4, sticky="ew")
        ctk.CTkLabel(guide, text="⚡ Tilt & Hold = Continuous Action (Scroll/Volume)  |  Flick = Quick Action  |  🔥 Flick + Tilt-Hold = Alt+Tab Switcher",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color="#3498db").pack(padx=10, pady=6)

        # Event log
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=4, column=0, padx=20, pady=(5, 15), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_frame, text="Live Activity Log",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0,
                                                                     padx=10, pady=5,
                                                                     sticky="w")
        self.txt_log = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_log.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_app)

    def _stat(self, parent, col, title, initial):
        box = ctk.CTkFrame(parent)
        box.grid(row=0, column=col, padx=4, pady=6, sticky="ew")
        ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="gray").pack(padx=4, pady=(4, 0))
        val = ctk.CTkLabel(box, text=initial, font=ctk.CTkFont(size=12, weight="bold"))
        val.pack(padx=4, pady=(0, 4))
        return val

    def _refresh_app(self):
        app = get_foreground_app()
        profile = resolve_profile(app)
        short_app = app if len(app) <= 28 else app[:25] + "..."
        self.lbl_app.configure(text=short_app or "—")
        self.lbl_profile.configure(text=profile.upper())
        self.after(400, self._refresh_app)

    def _on_calibrate(self):
        if self.connected:
            self.bridge.send_command("CAL")
            self._append_log("[SYS] Sent sensor zero-calibration command (hold device level/neutral)...")
        else:
            self._append_log("[SYS] Connect to device before calibrating.")

    def _toggle_connect(self):
        if not self.connected:
            port = self.entry_port.get().strip()
            try:
                self.bridge.connect(port)
                self.bridge.start()
                self.connected = True
                self.btn_connect.configure(text="Disconnect", fg_color="crimson")
                self.lbl_status.configure(text=f"Connected ({port})", text_color="#2ecc71")
                self._append_log(f"[SYS] Connected to {port} at 9600 baud")
            except Exception as e:
                self.lbl_status.configure(text="Error", text_color="red")
                self._append_log(f"[ERROR] Could not open {port}: {e}")
        else:
            self.bridge.close()
            self.connected = False
            self.btn_connect.configure(text="Connect", fg_color=["#3B8ED0", "#1F6AA5"])
            self.lbl_status.configure(text="Disconnected", text_color="gray")
            self._append_log("[SYS] Disconnected")

    def _on_event(self, kind, payload):
        self.after(0, self._apply_event, kind, payload)

    def _apply_event(self, kind, payload):
        if kind == "telem":
            parts = dict(kv.split("=") for kv in payload.split(",") if "=" in kv)
            r = parts.get("roll", "0")
            p = parts.get("pitch", "0")
            gx = parts.get("gx", "0")
            gy = parts.get("gy", "0")
            gz = parts.get("gz", "0")
            self.lbl_angles.configure(text=f"{r}° / {p}°")
            self.lbl_gyro.configure(text=f"{gx}, {gy}, {gz}")
        elif kind in ("gesture", "combo"):
            g = payload["gesture"]
            m = payload["macro"]
            self.lbl_last_g.configure(text=g)
            self.lbl_macro.configure(text=m)
            prefix = "[COMBO]  " if kind == "combo" else "[GESTURE]"
            self._append_log(f"{prefix} {g:<18} -> {m:<28} (Profile: {payload['profile']})")
        elif kind == "status":
            self._append_log(f"[ESP]    {payload}")
        elif kind == "error":
            self._append_log(f"[ERROR]  {payload}")

    def _append_log(self, text):
        self.txt_log.insert("end", f"{text}\n")
        self.txt_log.see("end")

    def _on_close(self):
        if self.connected:
            self.bridge.close()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
