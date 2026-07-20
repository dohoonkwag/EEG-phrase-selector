#include <SoftwareSerial.h>

// Because I'm connecting the arduino to my computer, and having it interact
// with a python script I'm running on there, the arduino uses its built in
// TX and RX pins (0 and 1) to communicate with my computer. The
// following code creates a second serial port using different digital pins
// that I will use to communicate with the HC-05 Bluetooth module.
SoftwareSerial bluetooth(2, 3); // Pin 2 is RX

void setup() {
  Serial.begin(115200); 
  bluetooth.begin(57600); 
}


// The Mindwave Mobile 2 samples data at 512 Hz. Instead of sending each point
// by itself, it sends the data in packets. Here is the structure of each packet:
// byte 0: 0xAA               signals start of a packet
// byte 1: 0xAA               verifies start of a packet
// byte 2: 0x04               indicates payload length (4 bytes)
// byte 3: 0x80               0x80 indicates that the data is raw EEG wave value
// byte 4: 0x02               indicates value length (2 bytes)
// byte 5: 0xXX (variable)    upper 8 bits of 16-bit EEG value
// byte 6: 0xXX (variable)    lower 8 bits of 16-bit EEG value
// btye 7: 0xXX (variable)    checksum to validate packet isn't corrupted


void loop() {
  if (bluetooth.available() > 2) {
    if (bluetooth.read() == 170 && bluetooth.read() == 170) {
      byte payloadLength = bluetooth.read();
      if (bluetooth.read() == 128) { // Raw wave code
        byte rawLength = bluetooth.read(); 
        byte highByte = bluetooth.read();
        byte lowByte = bluetooth.read();
        
        int rawWave = (highByte << 8) | lowByte; // bitwise OR to stitch together highByte and lowByte
        if (rawWave >= 32768) rawWave -= 65536;
        
        Serial.println(rawWave); // Send to Python
      }
    }
  }
}
