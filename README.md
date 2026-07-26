# EEG-phrase-selector

A bilingual assistive communication system that translates electrooculography (EOG) signals into spoken phrases using a single dry electrode on the forehead ($\text{FP1}$). 

This project was built to demonstrate how blinks can be decoded in real-time to drive a hands-free user interface without relying on proprietary black-box metrics.


## System Architecture & Hardware Bridge

Connecting to the **NeuroSky MindWave Mobile 2** was a significant hurdle because the device lacks recent developer support. 

### Step-by-Step Hardware Setup & Pairing Procedure

1. **Obtain MindWave MAC Address:** Turn the MindWave Mobile 2 on (the light should be blue) and use a Bluetooth scanner to obtain its 12-digit MAC address (e.g., `00:11:22:33:44:55`). Or, if you open the battery compartment of the MindWave Mobile 2, there might be a sticker with a barcode and the MAC address as well.
2. **Configure HC-05 in AT Mode:**
   * Upload a basic SerialPassthrough sketch to the Arduino 
   * Connect the HC-05 module to an Arduino Uno (using `SoftwareSerial` on pins 10/11) and hold down the button on the HC-05 module WHILE powering up the Arduino to enter AT command mode. The light should be blinking slowly.
   * Wipe the HC-05 back to factory defaults: `AT+ORGL`
   * Set HC-05 to Master Mode: `AT+ROLE=1`
   * Set Connection Mode to fixed MAC address: `AT+CMODE=0`
   * The MindWave has a hardcoded passcode of 0000: `AT+PSWD="0000"`
   * Lock the hardware communication speed to match the MindWave: `AT+UART=57600,0,0`
   * Tell the module to lock its focus entirely onto a single device (the MindWave): `AT+CMODE=0`
   * Bind to MindWave MAC address: `AT+BIND=0011,22,334455` *(replace colons with commas)*
3. **Hardware Data Forwarding:**
   * Upload the raw_eeg_stream.ino sketch to the Arduino, which will send the data to your computer (which should be running the v1-final.py program)
4. **Serial Streaming to Python:**
   * The Python backend opens `/dev/cu.usbmodem1101` at `115200` baud.


### Digital Signal Processing Pipeline
1. **Bandpass Filtering:** Raw data passes through a 2nd-order Butterworth 1–15 Hz bandpass filter to eliminate baseline DC drift and high-frequency noise.
2. **Rolling Amplitude Window:** A 250 ms rolling window measures Peak-to-Peak amplitude to detect voltage swings exceeding an adjustable threshold.
3. **Biphasic Rebound Debouncing:** Physical blinks often create a positive peak followed by a negative overshoot. To prevent a single blink from double-counting, the engine enforces a **hard lockout window**.

---

## Hands-Free Navigation & State Machine
* **Double Blink ($\text{Count} = 2$):** Advances the highlighted menu index down by 1 option. Confirmed by a $600\text{ Hz}$ scroll chime.
* **4-Blink Sequence ($\text{Count} = 4$):** Selects the active phrase. Confirmed by a $900\text{ Hz}$ selection chime, triggering TTS output.
* **Invalid Count ($1, 3, \text{or } 5+$):** Discarded on pattern timeout. Confirmed with a low $300\text{ Hz}$ discard tone.