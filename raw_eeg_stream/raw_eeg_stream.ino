#include <SoftwareSerial.h>

SoftwareSerial bluetooth(2, 3); // Pin 2 is RX

void setup() {
  Serial.begin(115200); 
  bluetooth.begin(57600); 
}

void loop() {
  if (bluetooth.available() > 2) {
    if (bluetooth.read() == 170 && bluetooth.read() == 170) {
      byte payloadLength = bluetooth.read();
      if (bluetooth.read() == 128) { // Raw wave code
        byte rawLength = bluetooth.read(); 
        byte highByte = bluetooth.read();
        byte lowByte = bluetooth.read();
        
        int rawWave = (highByte << 8) | lowByte;
        if (rawWave >= 32768) rawWave -= 65536;
        
        Serial.println(rawWave); // Send to Python
      }
    }
  }
}