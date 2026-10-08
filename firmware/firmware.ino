#include <Arduino.h>
#include <Wire.h>
#include <math.h>

// I2C Pin definitions for ESP8266
#ifndef D2
#define D2 4 // SDA
#endif
#ifndef D1
#define D1 5 // SCL
#endif

// MPU6050 Default I2C Address
uint8_t mpu_addr = 0x68;

// Gesture thresholds - adjusted for ~25% gentler sensitivity
const float TILT_ACTIVATE_DEG      = 26.0;     // Slightly higher deadzone (was 22.0) to prevent accidental triggers
const float TILT_RELEASE_DEG       = 15.0;     // Clean release threshold (was 12.0)
const unsigned long TILT_REPEAT_MS = 275;      // Throttled hold repeat rate by ~25% (was 200ms -> 275ms)

// Gyroscope flick / swipe detection
const float GYRO_FLICK_THRESHOLD_DPS = 210.0; // Slightly cleaner flick threshold (was 180.0)
const unsigned long FLICK_COOLDOWN_MS  = 350;  // Debounce cooldown window (was 300ms)
const unsigned long TILT_SUPPRESS_AFTER_FLICK_MS = 180; // Rebound suppression window
enum TiltState {
    TILT_NONE,
    TILT_LEFT,
    TILT_RIGHT,
    TILT_FORWARD,
    TILT_BACKWARD
};

TiltState currentTilt = TILT_NONE;
unsigned long lastTiltRepeatTime = 0;

unsigned long lastFlickTime = 0;
unsigned long suppressTiltUntil = 0;
unsigned long lastTelemTime = 0;

// Calibration baseline offsets
float base_roll  = 0.0;
float base_pitch = 0.0;
float base_gx    = 0.0;
float base_gy    = 0.0;
float base_gz    = 0.0;

// Write single byte to I2C register
bool writeMPU(uint8_t reg, uint8_t data) {
    Wire.beginTransmission(mpu_addr);
    Wire.write(reg);
    Wire.write(data);
    return (Wire.endTransmission() == 0);
}

// Read raw sensor data from MPU6050 (14 bytes starting at 0x3B)
bool readMPURaw(int16_t &ax, int16_t &ay, int16_t &az,
                int16_t &gx, int16_t &gy, int16_t &gz) {
    Wire.beginTransmission(mpu_addr);
    Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) {
        return false;
    }
    if (Wire.requestFrom((uint8_t)mpu_addr, (uint8_t)14) != 14) {
        return false;
    }
    ax = (Wire.read() << 8) | Wire.read();
    ay = (Wire.read() << 8) | Wire.read();
    az = (Wire.read() << 8) | Wire.read();
    int16_t raw_temp = (Wire.read() << 8) | Wire.read(); // temperature (unused)
    gx = (Wire.read() << 8) | Wire.read();
    gy = (Wire.read() << 8) | Wire.read();
    gz = (Wire.read() << 8) | Wire.read();
    return true;
}

void calibrateSensor(int samples = 50) {
    float sum_roll = 0;
    float sum_pitch = 0;
    float sum_gx = 0;
    float sum_gy = 0;
    float sum_gz = 0;
    int valid = 0;

    for (int i = 0; i < samples; i++) {
        int16_t raw_ax, raw_ay, raw_az, raw_gx, raw_gy, raw_gz;
        if (readMPURaw(raw_ax, raw_ay, raw_az, raw_gx, raw_gy, raw_gz)) {
            float ax = (raw_ax / 8192.0) * 9.80665;
            float ay = (raw_ay / 8192.0) * 9.80665;
            float az = (raw_az / 8192.0) * 9.80665;
            float gx = raw_gx / 65.5;
            float gy = raw_gy / 65.5;
            float gz = raw_gz / 65.5;

            float r = atan2(ay, az) * 180.0 / PI;
            float p = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / PI;

            sum_roll += r;
            sum_pitch += p;
            sum_gx += gx;
            sum_gy += gy;
            sum_gz += gz;
            valid++;
        }
        delay(12);
    }

    if (valid > 0) {
        base_roll  = sum_roll / valid;
        base_pitch = sum_pitch / valid;
        base_gx    = sum_gx / valid;
        base_gy    = sum_gy / valid;
        base_gz    = sum_gz / valid;
    }
}

void setup() {
    Serial.begin(9600);
    delay(500);
    Serial.println();
    Serial.println("STATUS:INITIALIZING");

    Wire.begin(D2, D1);
    Wire.setClock(50000); // 50kHz for rock-solid stability
    delay(200);

    // Auto-detect & connect to MPU6050 (0x68 or 0x69)
    bool found = false;
    while (!found) {
        Wire.beginTransmission(0x68);
        if (Wire.endTransmission() == 0) {
            mpu_addr = 0x68;
            found = true;
            break;
        }
        Wire.beginTransmission(0x69);
        if (Wire.endTransmission() == 0) {
            mpu_addr = 0x69;
            found = true;
            break;
        }
        Serial.println("STATUS:SEARCHING_SENSOR");
        delay(400);
    }

    // Wake up MPU6050: write 0x00 to PWR_MGMT_1 (0x6B)
    writeMPU(0x6B, 0x00);
    delay(40);
    // Configure DLPF: 21Hz low-pass filter (0x1A = 0x03)
    writeMPU(0x1A, 0x03);
    // Configure Accel Range: +/- 4g (0x1C = 0x08)
    writeMPU(0x1C, 0x08);
    // Configure Gyro Range: +/- 500 deg/s (0x1B = 0x08)
    writeMPU(0x1B, 0x08);
    delay(40);

    // Baseline calibration (50 samples ~ 600ms)
    Serial.println("STATUS:CALIBRATING");
    calibrateSensor(50);

    Serial.println("STATUS:READY");
}

void loop() {
    unsigned long now = millis();

    // Check for incoming serial calibration commands
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd == "CAL" || cmd == "TARE" || cmd == "CALIBRATE") {
            currentTilt = TILT_NONE;
            Serial.println("STATUS:CALIBRATING");
            calibrateSensor(50);
            Serial.println("STATUS:READY");
        }
    }

    int16_t raw_ax, raw_ay, raw_az;
    int16_t raw_gx, raw_gy, raw_gz;

    if (!readMPURaw(raw_ax, raw_ay, raw_az, raw_gx, raw_gy, raw_gz)) {
        delay(10);
        return;
    }

    // Convert raw accel (+/- 4g range -> 8192 LSB/g) to m/s^2
    float ax = (raw_ax / 8192.0) * 9.80665;
    float ay = (raw_ay / 8192.0) * 9.80665;
    float az = (raw_az / 8192.0) * 9.80665;

    // Convert raw gyro (+/- 500 deg/s range -> 65.5 LSB/(deg/s))
    float gx = raw_gx / 65.5;
    float gy = raw_gy / 65.5;
    float gz = raw_gz / 65.5;

    // Compute roll and pitch from gravity vector
    float raw_roll  = atan2(ay, az) * 180.0 / PI;
    float raw_pitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / PI;

    // Apply baseline offset
    float roll  = raw_roll - base_roll;
    float pitch = raw_pitch - base_pitch;

    // Normalize angles to -180 .. +180
    while (roll > 180.0)  roll -= 360.0;
    while (roll < -180.0) roll += 360.0;
    while (pitch > 180.0)  pitch -= 360.0;
    while (pitch < -180.0) pitch += 360.0;

    // Cleaned gyro rates
    float gx_clean = gx - base_gx;
    float gy_clean = gy - base_gy;
    float gz_clean = gz - base_gz;

    // Telemetry stream at 10 Hz (every 100ms)
    if (now - lastTelemTime >= 100) {
        lastTelemTime = now;
        Serial.printf("TELEM:roll=%.1f,pitch=%.1f,gx=%.1f,gy=%.1f,gz=%.1f\n",
                      roll, pitch, gx_clean, gy_clean, gz_clean);
    }

    // Gyro-based Flick / Swipe detection
    if (now - lastFlickTime > FLICK_COOLDOWN_MS) {
        float absGx = fabs(gx_clean);
        float absGy = fabs(gy_clean);

        if (absGx > GYRO_FLICK_THRESHOLD_DPS && absGx > absGy * 1.2) {
            if (gx_clean > 0) {
                Serial.println("SWIPE_RIGHT");
            } else {
                Serial.println("SWIPE_LEFT");
            }
            lastFlickTime = now;
            suppressTiltUntil = now + TILT_SUPPRESS_AFTER_FLICK_MS;
        } else if (absGy > GYRO_FLICK_THRESHOLD_DPS && absGy > absGx * 1.2) {
            if (gy_clean > 0) {
                Serial.println("SWIPE_UP");
            } else {
                Serial.println("SWIPE_DOWN");
            }
            lastFlickTime = now;
            suppressTiltUntil = now + TILT_SUPPRESS_AFTER_FLICK_MS;
        }
    }

    // Tilt-and-Hold suppression during flick recovery
    if (now < suppressTiltUntil) {
        delay(10);
        return;
    }

    // State-Aware Tilt-and-Hold with clean Hysteresis
    if (currentTilt == TILT_NONE) {
        if (roll > TILT_ACTIVATE_DEG) {
            currentTilt = TILT_RIGHT;
            lastTiltRepeatTime = now;
            Serial.println("TILT_HOLD_RIGHT");
        } else if (roll < -TILT_ACTIVATE_DEG) {
            currentTilt = TILT_LEFT;
            lastTiltRepeatTime = now;
            Serial.println("TILT_HOLD_LEFT");
        } else if (pitch > TILT_ACTIVATE_DEG) {
            currentTilt = TILT_BACKWARD;
            lastTiltRepeatTime = now;
            Serial.println("TILT_HOLD_BACKWARD");
        } else if (pitch < -TILT_ACTIVATE_DEG) {
            currentTilt = TILT_FORWARD;
            lastTiltRepeatTime = now;
            Serial.println("TILT_HOLD_FORWARD");
        }
    } else {
        bool released = false;
        switch (currentTilt) {
            case TILT_RIGHT:
                if (roll < TILT_RELEASE_DEG) released = true;
                break;
            case TILT_LEFT:
                if (roll > -TILT_RELEASE_DEG) released = true;
                break;
            case TILT_BACKWARD:
                if (pitch < TILT_RELEASE_DEG) released = true;
                break;
            case TILT_FORWARD:
                if (pitch > -TILT_RELEASE_DEG) released = true;
                break;
            default:
                released = true;
                break;
        }

        if (released) {
            currentTilt = TILT_NONE;
            Serial.println("TILT_RELEASE");
        } else {
            // Continually repeat every TILT_REPEAT_MS
            if (now - lastTiltRepeatTime >= TILT_REPEAT_MS) {
                lastTiltRepeatTime = now;
                switch (currentTilt) {
                    case TILT_LEFT:     Serial.println("TILT_HOLD_LEFT"); break;
                    case TILT_RIGHT:    Serial.println("TILT_HOLD_RIGHT"); break;
                    case TILT_FORWARD:  Serial.println("TILT_HOLD_FORWARD"); break;
                    case TILT_BACKWARD: Serial.println("TILT_HOLD_BACKWARD"); break;
                    default: break;
                }
            }
        }
    }

    delay(10);
}
