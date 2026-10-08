#include <Wire.h>

void setup() {
    Serial.begin(9600);
    delay(500);
    Serial.println("\n=== Continuous I2C Probe ===");
    Wire.begin(D2, D1); // SDA = D2, SCL = D1
    Wire.setClock(50000);
}

void loop() {
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("[OK] Found device at 0x%02X\n", addr);
            found++;
        }
    }
    if (found == 0) {
        Serial.println("[BUS] No response on D2(SDA)/D1(SCL). Checking...");
    }
    delay(800);
}
