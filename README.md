# GestureHID — Context-Aware Inertial Gesture Input System

An edge-processed, low-latency inertial gesture recognition peripheral and autonomous host context bridge for dynamic application-specific macro execution.

---

## 🌟 Overview

**GestureHID** is a hardware-software system that transforms continuous 6-axis inertial motion (linear acceleration and angular rate) into instant keyboard, media, and workflow automation macros. 

Unlike conventional macro keypads with static bindings or camera-based gesture systems with high host CPU overhead, GestureHID processes all gesture classification (flicks, continuous tilts, and holds) directly at the microcontroller edge, streaming low-latency input reports to an autonomous host-side context bridge.

```
+-------------------+      I2C Bus      +---------------------+
|   MPU6050 IMU     | ----------------> | Microcontroller     |
| (6-Axis Acc/Gyro) |   (50-200 Hz)     | (Edge Gesture Core) |
+-------------------+                   +---------------------+
                                                   |
                                            Serial / HID
                                                   |
                                                   v
+-------------------+  Win32 / OS Focus +---------------------+
| Active App Focus  | <---------------- | Host Context Bridge |
| (Media, IDE, CAD) | ----------------> | (Python / CTk GUI)  |
+-------------------+   Dynamic Macro   +---------------------+
```

---

## 🚀 Key Features

- **Edge Gesture Classification**:
  - **Flick Gestures (Up, Down, Left, Right)**: High-speed angular velocity detection ($>200^\circ/\text{s}$) with cooldown debounce and rebound suppression.
  - **Continuous Tilt-and-Hold**: Variable/sustained hold state transitions with automatic repeat intervals for scrolling, volume scrubbing, and zoom.
  - **Multi-Gesture Modifier Combinations**: Multi-step gesture sequencing (e.g. Flick $\rightarrow$ Sustained Tilt) emulating native OS shortcuts (Alt+Tab app switching).
- **Autonomous Context Bridge**:
  - Automatically queries the active foreground application via Win32 API / OS window manager.
  - Dynamically remaps identical physical gestures to application-specific macro suites (e.g., Timeline Zoom in Premiere, Undo/Redo in Photoshop, Track Skip in Spotify, Tab Switching in VS Code / Chrome).
- **Live GUI Dashboard**:
  - Built with CustomTkinter featuring real-time connection status, detected gesture logs, active process tracking, and manual serial port selection.
- **Hardware Diagnostic Suite**:
  - Dedicated I2C diagnostic sketch to verify MPU6050 communication and bus address integrity.

---

## 🛠️ Hardware Requirements

| Component | Specification | Remarks |
| :--- | :--- | :--- |
| **Microcontroller** | ESP32 / ESP8266 / RP2040 | 3.3V logic level |
| **IMU Sensor** | MPU-6050 (6-DOF) | 3-axis Accelerometer + 3-axis Gyroscope |
| **Interface** | I2C (SDA / SCL) | $4.7\text{ k}\Omega$ pull-up resistors recommended |
| **Power Supply** | 5V VBUS stepped down to 3.3V | Regulated 3.3V supply rail |

### Pin Configuration (Default ESP8266 / NodeMCU)
- `SDA` $\rightarrow$ `GPIO 4` (D2)
- `SCL` $\rightarrow$ `GPIO 5` (D1)
- `VCC` $\rightarrow$ `3.3V`
- `GND` $\rightarrow$ `GND`

---

## 📂 Repository Structure

```
.
├── firmware/
│   └── firmware.ino          # Edge gesture recognition & I2C sampling firmware
├── host/
│   ├── bridge.py             # Context-aware macro engine & CustomTkinter GUI
│   └── requirements.txt      # Python host dependencies
├── i2c_diag/
│   └── i2c_diag.ino          # I2C bus scanner and hardware diagnostic tool
├── .gitignore
├── LICENSE
└── README.md
```

---

## ⚡ Quick Start

### 1. Flash the Firmware
1. Open `firmware/firmware.ino` in Arduino IDE or PlatformIO.
2. Select your board (e.g. NodeMCU 1.0 / ESP32 Dev Module).
3. Set the baud rate to `115200`.
4. Upload the sketch to your microcontroller.

*(Optional)* Run `i2c_diag/i2c_diag.ino` first to verify that the MPU6050 sensor responds at address `0x68` or `0x69`.

### 2. Set Up the Host Bridge
1. Navigate to the `host/` folder:
   ```bash
   cd host
   ```
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the host context bridge:
   ```bash
   python bridge.py
   ```
4. Select your serial COM port from the UI dropdown and click **Connect**.

---

## 🎯 Application Mapping Matrix

| Physical Gesture | General / Browser | Media (Spotify / VLC) | Creative / Design |
| :--- | :--- | :--- | :--- |
| **Flick Left** | Back / Previous Tab | Previous Track | Undo (`Ctrl+Z`) |
| **Flick Right** | Forward / Next Tab | Next Track | Redo (`Ctrl+Y`) |
| **Tilt Left (Hold)** | Scroll Left / Up | Volume Down | Decrease Brush Size |
| **Tilt Right (Hold)**| Scroll Right / Down | Volume Up | Increase Brush Size |
| **Flick + Tilt** | Window Switcher (`Alt+Tab`) | Playlist Scrub | Layer Navigation |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
