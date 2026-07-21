import serial
import time
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import welch, butter, lfilter

ARDUINO_PORT = '/dev/cu.usbmodem1101'
BAUD_RATE = 115200

FS = 512                        # MindWave sampling rate
WINDOW_SECONDS = 2.0            # 2 second EEG window
WINDOW_SIZE = int(FS * WINDOW_SECONDS)

FOCUS_THRESHOLD = 60.0          # Normalized target score (0-100)
HOLD_TIME_REQUIRED = 1.5        # Seconds to hold focus
SMOOTHING_ALPHA = 0.05          # Heavy Exponential Moving Average for smooth output

# Frequency bands
THETA_BAND = (4.0, 8.0)
ALPHA_BAND = (8.0, 12.0)
BETA_BAND  = (13.0, 30.0)

# 0.5 - 35 Hz Bandpass Filter
nyq = 0.5 * FS
b_band, a_band = butter(2, [0.5 / nyq, 35.0 / nyq], btype='band')

# Serial setup
try:
    ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=0.1)
    ser.reset_input_buffer()
    print(f"Connected to {ARDUINO_PORT}.\n")
except Exception as e:
    print(f"Serial Connection Error: {e}")
    exit()



eeg_buffer = np.zeros(WINDOW_SIZE)
focus_history = [50.0] * 60
baseline_history = []           # Stores last 30 seconds of log-ratios

smoothed_focus = 50.0
focus_start_time = None
total_selections = 0

plt.ion()
fig, ax = plt.subplots(figsize=(10, 5))
fig.patch.set_facecolor('#121212')
ax.set_facecolor('#1E1E1E')

line_focus, = ax.plot(focus_history, color='#00E5FF', linewidth=2.5, label='Normalized Focus Score')
ax.axhline(y=FOCUS_THRESHOLD, color='#FFEA00', linestyle='--', linewidth=1.5, label='Threshold')

ax.set_ylim(0, 105)
ax.set_ylabel('Focus Score (0 - 100%)', color='white')
ax.set_xlabel('Rolling History', color='white')
ax.set_title('Raw EEG Concentration Decoder!', color='white', fontsize=12, fontweight='bold')
ax.tick_params(colors='white')
ax.grid(True, color='#333333', linestyle=':')
ax.legend(loc='upper left', facecolor='#222222', edgecolor='none', labelcolor='white')

hud_text = ax.text(0.5, 0.85, "Relax, calibrating!", 
                   transform=ax.transAxes, color='#00FF66', 
                   ha='center', fontsize=12, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', alpha=0.85))

plt.draw()
plt.pause(0.1)

def calculate_band_power(psd, freqs, band):
    idx = np.logical_and(freqs >= band[0], freqs <= band[1])
    return np.sum(psd[idx]) + 1e-10



try:
    sample_counter = 0
    
    while True:
        if ser.in_waiting:
            raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not raw_line:
                continue

            if "RAW:" in raw_line:
                raw_line = raw_line.split("RAW:")[1].strip()
                
            try:
                val = int(raw_line)
            except ValueError:
                continue

            # Push to rolling window
            eeg_buffer = np.roll(eeg_buffer, -1)
            eeg_buffer[-1] = val
            sample_counter += 1

            # Process spectral data every 32 samples
            if sample_counter % 32 == 0:
                # Bandpass filter
                clean_signal = lfilter(b_band, a_band, eeg_buffer)
                
                # nperseg=256 averages 7 overlapping sub-windows to reduce variance
                freqs, psd = welch(clean_signal, fs=FS, nperseg=256, window='hann')

                # Band Powers
                theta_p = calculate_band_power(psd, freqs, THETA_BAND)
                alpha_p = calculate_band_power(psd, freqs, ALPHA_BAND)
                beta_p  = calculate_band_power(psd, freqs, BETA_BAND)

                # Compute Log Ratio: ln(Beta) - ln(Alpha + Theta)
                log_ratio = np.log(beta_p) - np.log(alpha_p + theta_p)

                # Adaptive Baseline Normalization
                # Store recent ratios (last 30 seconds = ~480 data points)
                baseline_history.append(log_ratio)
                if len(baseline_history) > 480:
                    baseline_history.pop(0)

                # Measure current ratio relative to the personal mean and range
                mean_ratio = np.mean(baseline_history)
                std_ratio = np.std(baseline_history) + 1e-5  # avoid div by zero

                # Map Z-Score to 0-100 scale (Mean = 50%, ±2 Standard Deviations = 0% to 100%)
                z_score = (log_ratio - mean_ratio) / std_ratio
                normalized_score = np.clip(50.0 + (z_score * 20.0), 0.0, 100.0)

                # Apply Heavy EMA Filter
                smoothed_focus = (SMOOTHING_ALPHA * normalized_score) + ((1 - SMOOTHING_ALPHA) * smoothed_focus)

                focus_history.pop(0)
                focus_history.append(smoothed_focus)

                # Checking the hold Logic
                current_time = time.time()
                
                if smoothed_focus >= FOCUS_THRESHOLD:
                    if focus_start_time is None:
                        focus_start_time = current_time
                    
                    elapsed = current_time - focus_start_time
                    progress_pct = min(100, int((elapsed / HOLD_TIME_REQUIRED) * 100))
                    
                    hud_text.set_text(f"Focus: {progress_pct}% [{elapsed:.1f}s / {HOLD_TIME_REQUIRED}s]")
                    hud_text.set_color('#FFEA00')

                    if elapsed >= HOLD_TIME_REQUIRED:
                        total_selections += 1
                        print(f"[{time.strftime('%H:%M:%S')}] Focus confirmed! #{total_selections} (Level: {smoothed_focus:.1f})")
                        hud_text.set_text(f"Focus confirmed! (#{total_selections})")
                        hud_text.set_color('#FF4081')
                        
                        focus_start_time = None
                        time.sleep(1.0)
                else:
                    focus_start_time = None
                    hud_text.set_text(f"Focus Score: {smoothed_focus:.1f}% / {FOCUS_THRESHOLD}%")
                    hud_text.set_color('#00FF66')

                # Update Plot
                line_focus.set_ydata(focus_history)
                plt.pause(0.001)

except KeyboardInterrupt:
    print(f"\nFinished. Total Selections: {total_selections}")
finally:
    ser.close()