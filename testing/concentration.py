import serial
import time
import os
import sys
import numpy as np
from scipy.signal import welch, butter, lfilter


ARDUINO_PORT = '/dev/cu.usbmodem1101' 
BAUD_RATE = 115200

FS = 512                        # Sampling rate (Hz)
WINDOW_SECONDS = 2.0            # Analysis window
WINDOW_SIZE = int(FS * WINDOW_SECONDS)

CALIB_PHASE_DURATION = 15.0     # Duration (sec) for each training state

# Bands & Filter
ALPHA_BAND = (8.0, 12.0)
BETA_BAND  = (13.0, 30.0)
TOTAL_BAND = (2.0, 35.0)

nyq = 0.5 * FS
b_band, a_band = butter(2, [2.0 / nyq, 35.0 / nyq], btype='band')

def generate_tone_wav(filename, freq_hz, duration_sec, volume=0.18):
    sample_rate = 44100
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
    tone = np.sin(2 * np.pi * freq_hz * t) * volume
    audio_data = (tone * 32767).astype(np.int16)
    
    import wave
    with wave.open(filename, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

generate_tone_wav("cue_math.wav", freq_hz=1000, duration_sec=0.40)
generate_tone_wav("cue_relax.wav", freq_hz=450, duration_sec=0.40)
generate_tone_wav("cue_done.wav", freq_hz=1200, duration_sec=0.50)
generate_tone_wav("focus_loop_chunk.wav", freq_hz=880, duration_sec=0.18, volume=0.15)

def play_audio(filename):
    os.system(f"afplay {filename} &")

def play_focus_chunk():
    os.system("afplay focus_loop_chunk.wav &")

try:
    ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=0.05)
    ser.reset_input_buffer()
    print(f"Connected to {ARDUINO_PORT}.\n")
except Exception as e:
    print(f"Serial Connection Error: {e}")
    exit()

def calculate_band_power(psd, freqs, band):
    idx = np.logical_and(freqs >= band[0], freqs <= band[1])
    return np.sum(psd[idx]) + 1e-10

eeg_buffer = np.zeros(WINDOW_SIZE)
serial_data_buffer = ""

def read_latest_samples():
    global serial_data_buffer
    samples = []
    
    if ser.in_waiting > 0:
        chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        serial_data_buffer += chunk
        
        lines = serial_data_buffer.split('\n')
        serial_data_buffer = lines[-1]  # Keep incomplete tail
        
        for line in lines[:-1]:
            line = line.strip()
            if "RAW:" in line:
                line = line.split("RAW:")[1].strip()
            try:
                samples.append(int(line))
            except ValueError:
                continue
    return samples


def record_training_data(phase_name, duration_sec, cue_wav, default_fallback):
    global eeg_buffer
    
    print(f"\nGet ready: {phase_name.upper()} in 3 seconds")
    for i in range(3, 0, -1):
        print(f"     Starting in {i}...", end='\r')
        time.sleep(1.0)
    
    play_audio(cue_wav)
    print(f"\nRecording {phase_name.upper()} now ({duration_sec}s)")
    
    ratios = []
    sample_counter = 0
    start_time = time.time()
    
    while time.time() - start_time < duration_sec:
        new_vals = read_latest_samples()
        for val in new_vals:
            eeg_buffer = np.roll(eeg_buffer, -1)
            eeg_buffer[-1] = val
            sample_counter += 1

            if sample_counter % 32 == 0:
                detrended = eeg_buffer - np.mean(eeg_buffer)
                if np.ptp(detrended) > 1500:
                    continue

                clean_signal = lfilter(b_band, a_band, eeg_buffer)
                freqs, psd = welch(clean_signal, fs=FS, nperseg=256, window='hann')

                alpha_p = calculate_band_power(psd, freqs, ALPHA_BAND)
                beta_p  = calculate_band_power(psd, freqs, BETA_BAND)
                
                # Beta / Alpha Ratio suppresses relaxed Alpha waves
                log_ratio = np.log(beta_p) - np.log(alpha_p)
                if not np.isnan(log_ratio) and not np.isinf(log_ratio):
                    ratios.append(log_ratio)

                time_left = max(0.0, duration_sec - (time.time() - start_time))
                sys.stdout.write(f"\r progress: [{int(time_left)}s left] Valid Segments: {len(ratios)}")
                sys.stdout.flush()

        time.sleep(0.005)  # Yield CPU safely

    print(f"\n--- Finished {phase_name} ({len(ratios)} valid segments captured) ---")
    
    if len(ratios) == 0:
        print(f"No clean segments captured. Using fallback default ({default_fallback}).")
        return default_fallback
    
    mean_val = float(np.mean(ratios))
    return default_fallback if np.isnan(mean_val) else mean_val

print("High Chime -> Mental Math")
print("Low Chime  -> Relaxed Idle")

input("Press enter!")

math_ratio_mean  = record_training_data("Active Math", CALIB_PHASE_DURATION, "cue_math.wav", default_fallback=0.20)
time.sleep(3.0)
relax_ratio_mean = record_training_data("Relaxed Idle", CALIB_PHASE_DURATION, "cue_relax.wav", default_fallback=-0.40)

CUSTOM_THRESHOLD = (math_ratio_mean + relax_ratio_mean) / 2.0


print(f"Training complete!")

# Hysteresis Bounds (+/- 0.08 deadzone around threshold)
HYSTERESIS_ON  = CUSTOM_THRESHOLD + 0.08
HYSTERESIS_OFF = CUSTOM_THRESHOLD - 0.08

print(f"Math Ratio Mean (Beta/Alpha):  {math_ratio_mean:.4f}")
print(f"Relax Ratio Mean (Beta/Alpha): {relax_ratio_mean:.4f}")
print(f"Calculated threshold: {CUSTOM_THRESHOLD:.4f}")
print(f"Hysteresis Bounds: ON >= {HYSTERESIS_ON:.4f} | OFF <= {HYSTERESIS_OFF:.4f}")


play_audio("cue_done.wav")
time.sleep(1.0)


median_buffer = [relax_ratio_mean] * 12
smoothed_ratio = relax_ratio_mean
is_concentrating = False
last_focus_beep_time = 0
sample_counter = 0

# Automatically detect if Math produces a higher or lower score than Relax
math_is_higher = math_ratio_mean > relax_ratio_mean

print("Real time testing started!")
print("Close eyes. Do math to trigger the tone!\n")

def draw_ascii_bar(val, thresh, math_m, relax_m):
    min_v = min(math_m, relax_m) - 0.3
    max_v = max(math_m, relax_m) + 0.3
    
    norm_val = np.clip((val - min_v) / (max_v - min_v), 0, 1)
    norm_thr = np.clip((thresh - min_v) / (max_v - min_v), 0, 1)
    
    bar_length = 30
    val_pos = int(norm_val * bar_length)
    thr_pos = int(norm_thr * bar_length)
    
    bar = []
    for i in range(bar_length):
        if i == thr_pos:
            bar.append('|')
        elif i < val_pos:
            bar.append('█')
        else:
            bar.append('░')
    return "".join(bar)

try:
    while True:
        new_vals = read_latest_samples()
        
        for val in new_vals:
            eeg_buffer = np.roll(eeg_buffer, -1)
            eeg_buffer[-1] = val
            sample_counter += 1

            if sample_counter % 32 == 0:
                detrended = eeg_buffer - np.mean(eeg_buffer)
                if np.ptp(detrended) > 1500:
                    sys.stdout.write("\r [rejected because of artifact]")
                    sys.stdout.flush()
                    continue

                clean_signal = lfilter(b_band, a_band, eeg_buffer)
                freqs, psd = welch(clean_signal, fs=FS, nperseg=256, window='hann')

                alpha_p = calculate_band_power(psd, freqs, ALPHA_BAND)
                beta_p  = calculate_band_power(psd, freqs, BETA_BAND)
                
                log_ratio = np.log(beta_p) - np.log(alpha_p)

                if np.isnan(log_ratio) or np.isinf(log_ratio):
                    continue

                median_buffer.append(log_ratio)
                if len(median_buffer) > 12:
                    median_buffer.pop(0)
                med_val = np.median(median_buffer)

                smoothed_ratio = (0.05 * med_val) + (0.95 * smoothed_ratio)
                now = time.time()

                # Dynamic Hysteresis State Machine (Respects Directionality)
                if math_is_higher:
                    if not is_concentrating and smoothed_ratio >= HYSTERESIS_ON:
                        is_concentrating = True
                    elif is_concentrating and smoothed_ratio <= HYSTERESIS_OFF:
                        is_concentrating = False
                else:
                    if not is_concentrating and smoothed_ratio <= HYSTERESIS_OFF:
                        is_concentrating = True
                    elif is_concentrating and smoothed_ratio >= HYSTERESIS_ON:
                        is_concentrating = False

                meter_bar = draw_ascii_bar(smoothed_ratio, CUSTOM_THRESHOLD, math_ratio_mean, relax_ratio_mean)

                if is_concentrating:
                    status_str = f"Doing math!  [{meter_bar}] {smoothed_ratio:.2f}"
                    if now - last_focus_beep_time >= 0.16:
                        play_focus_chunk()
                        last_focus_beep_time = now
                else:
                    status_str = f"Relaxed! [{meter_bar}] {smoothed_ratio:.2f}"

                sys.stdout.write(f"\r {status_str}   ")
                sys.stdout.flush()

        time.sleep(0.005)

except KeyboardInterrupt:
    print("\nTerminal BCI Session ended.")
finally:
    ser.close()