import serial
import time
import numpy as np
from scipy.signal import butter, lfilter, iirnotch
import matplotlib.pyplot as plt

ARDUINO_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE = 115200

FS = 512                        # Sampling rate (Hz)
DISPLAY_SECONDS = 2.0
BUFFER_SIZE = int(FS * DISPLAY_SECONDS)

LOW_CUT = 1.0                   # Cut baseline drift (< 1 Hz)
HIGH_CUT = 12.0                 # Cut muscle noise (> 12 Hz)
FILTER_ORDER = 4

MAX_ALLOWED_STD = 350.0         # Standard deviation cap (Anything > 350 is a disconnect blowout)
RAW_SATURATION_LIMIT = 1800     # Absolute raw limit indicating bad skin contact

BLINK_THRESHOLD = 380.0         # Trigger cutoff
REFRACTORY_SAMPLES = int(FS * 0.50)  # 500ms lockout (~256 samples)
MAX_BLINK_DURATION = int(FS * 0.40)  # 400ms max allowed pulse width

# Filter setup (Bandpass + 60Hz Notch)
def create_filters(fs):
    nyquist = 0.5 * fs
    
    # 4th-order Bandpass (1 - 12 Hz)
    low = LOW_CUT / nyquist
    high = HIGH_CUT / nyquist
    b_band, a_band = butter(FILTER_ORDER, [low, high], btype='band')
    
    # 60Hz Notch Filter to reject electronic noise
    b_notch, a_notch = iirnotch(60.0 / nyquist, Q=30.0)
    
    return b_band, a_band, b_notch, a_notch

b_band, a_band, b_notch, a_notch = create_filters(FS)

def apply_dsp_chain(data):
    # Apply notch filter first, then bandpass
    notch_filtered = lfilter(b_notch, a_notch, data)
    return lfilter(b_band, a_band, notch_filtered)

# Serial initiatlization
try:
    ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=0.1)
    print(f"Running!\n")
except Exception as e:
    print(f"Serial Connection Error: {e}")
    exit()


# Setting up buffers and plot setup
raw_buffer = np.zeros(BUFFER_SIZE)
filtered_buffer = np.zeros(BUFFER_SIZE)

refractory_counter = 0
above_threshold_duration = 0
total_blinks = 0
start_time = time.time()

# Setup Visualization
plt.ion()
fig, (ax_raw, ax_filt) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
fig.patch.set_facecolor('#121212')

# Top Plot
ax_raw.set_facecolor('#1E1E1E')
line_raw, = ax_raw.plot(raw_buffer, color='#00E5FF', linewidth=1.0, label='Raw EEG')
ax_raw.set_ylim(-1200, 1200)
ax_raw.set_ylabel('Raw Value', color='white')
ax_raw.set_title('Blink Detector (With Contact Quality Gate)', color='white', fontsize=12, fontweight='bold')
ax_raw.tick_params(colors='white')
ax_raw.grid(True, color='#333333', linestyle=':')

# Bottom Plot
ax_filt.set_facecolor('#1E1E1E')
line_filt, = ax_filt.plot(filtered_buffer, color='#FF4081', linewidth=1.5, label='Filtered (1-12 Hz + 60Hz Notch)')
ax_filt.axhline(y=BLINK_THRESHOLD, color='#FFEA00', linestyle='--', linewidth=1.5, label='Threshold')
ax_filt.axhline(y=-BLINK_THRESHOLD, color='#FFEA00', linestyle='--', linewidth=1.5)
ax_filt.set_ylim(-600, 600)
ax_filt.set_ylabel('Filtered Volts', color='white')
ax_filt.set_xlabel(f'Sample Window ({BUFFER_SIZE} samples @ 512Hz)', color='white')
ax_filt.tick_params(colors='white')
ax_filt.grid(True, color='#333333', linestyle=':')
ax_filt.legend(loc='upper right', facecolor='#222222', edgecolor='none', labelcolor='white')

# Display
hud_text = ax_raw.text(0.5, 0.88, "Status: Ready", 
                       transform=ax_raw.transAxes, color='#00FF66', 
                       ha='center', fontsize=11, fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.4', facecolor='#000000', alpha=0.8))

print('Begin!')


try:
    sample_counter = 0
    
    while True:
        if ser.in_waiting:
            line_str = ser.readline().decode('utf-8', errors='ignore').strip()
            
            if line_str.startswith("RAW:"):
                line_str = line_str.split(":")[1]
                
            try:
                val = int(line_str)
            except ValueError:
                continue

            # Push sample to rolling array
            raw_buffer = np.roll(raw_buffer, -1)
            raw_buffer[-1] = val
            sample_counter += 1

            # Process every 8 samples
            if sample_counter % 8 == 0:
                filtered_buffer = apply_dsp_chain(raw_buffer)
                
                # Check recent 0.25s slice
                recent_raw = raw_buffer[-128:]
                recent_filt = filtered_buffer[-128:]
                
                raw_max = np.max(np.abs(recent_raw))
                filt_std = np.std(recent_filt)

                # Signal quality check
                if raw_max > RAW_SATURATION_LIMIT or filt_std > MAX_ALLOWED_STD:
                    hud_text.set_text("Bad electrode contact :(")
                    hud_text.set_color('#FF3333')
                    above_threshold_duration = 0
                    refractory_counter = int(FS * 0.2)  # Short pause until signal settles
                    
                # debounced blink detection
                elif refractory_counter > 0:
                    refractory_counter -= 8
                    hud_text.set_text(f"Lockout! (Cooldown: {refractory_counter} samples)")
                    hud_text.set_color('#FFEA00')
                
                else:
                    latest_val = abs(filtered_buffer[-1])
                    
                    if latest_val > BLINK_THRESHOLD:
                        above_threshold_duration += 8
                    else:
                        if 0 < above_threshold_duration <= MAX_BLINK_DURATION:
                            total_blinks += 1
                            elapsed = time.time() - start_time
                            refractory_counter = REFRACTORY_SAMPLES  # 500ms lockout
                            
                            print(f"[{elapsed:06.2f}s] | Valid blink #{total_blinks} | Duration: {above_threshold_duration} samples")
                            hud_text.set_text(f"Blink detected! (#{total_blinks})")
                            hud_text.set_color('#FF4081')
                            
                        elif above_threshold_duration > MAX_BLINK_DURATION:
                            hud_text.set_text("BAD! Muscle Noise")
                            hud_text.set_color('#FF9900')
                            refractory_counter = int(FS * 0.3)
                            
                        above_threshold_duration = 0

                # Clear status text when idling safely
                if refractory_counter <= 0 and above_threshold_duration == 0 and filt_std <= MAX_ALLOWED_STD:
                    hud_text.set_text("Good Contact!")
                    hud_text.set_color('#00FF66')

                # Render updates
                if sample_counter % 32 == 0:
                    line_raw.set_ydata(raw_buffer)
                    line_filt.set_ydata(filtered_buffer)
                    fig.canvas.draw()
                    fig.canvas.flush_events()

except KeyboardInterrupt:
    print(f"\nFinished hurray! Total Blinks: {total_blinks}")
finally:
    ser.close()