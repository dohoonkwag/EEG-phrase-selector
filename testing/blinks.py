"""
Trying to extract different metrics (concentration, meditation, or eyes open eyes closed) from pure passive EEG
from a single FP1 dry electrode to drive a phrase selector seems to have hit a physiological wall.
To build a project that actually works and has zero false triggers, I'm going to temporarily abandon this approach
and pivot to active, high-signal-to-noise gestures like vertical eye movements.

Blinking would in theory produce a much more crisp and un-missable (maybe 150-300 microvolt) pulse in the TIME domain, 
that is detectable with the single FP1 electrode.

This is a script I am making to test if blinking is actually a high-signal-to-noise physiological 
gesture that is consistently capturable with the Neurosky Mindwave Mobile 2.
"""

import serial
import time
import subprocess
import os
import tempfile
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from scipy.signal import butter, lfilter

PORT = '/dev/cu.usbmodem1101'
BAUD = 115200

FS = 512 
WIN_LEN = int(FS * 0.25)   # 250ms window
PLOT_SAMPLES = FS * 4      
METRIC_SAMPLES = 120       

# 1-15 Hz Bandpass filter
nyq = 0.5 * FS
b_bp, a_bp = butter(2, [1.0 / nyq, 15.0 / nyq], btype='band')

def make_cue(filename, freq_hz, duration_sec=0.15, volume=0.2):
    sr = 44100
    t = np.linspace(0, duration_sec, int(sr * duration_sec), False)
    tone = np.sin(2 * np.pi * freq_hz * t) * volume
    fade = int(sr * 0.005)
    tone[:fade] *= np.linspace(0, 1, fade)
    tone[-fade:] *= np.linspace(1, 0, fade)
    
    filepath = os.path.join(tempfile.gettempdir(), filename)
    import wave
    with wave.open(filepath, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((tone * 32767).astype(np.int16).tobytes())
    return filepath

click_cue = make_cue("blink_click.wav", 1000, 0.1)

def play_sound(filepath):
    subprocess.Popen(["afplay", filepath])

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    ser.reset_input_buffer()
    print(f"Connected to {PORT}")
except Exception as err:
    print(f"Connection failed: {err}")
    exit()

def get_raw_samples():
    samples = []
    if ser.in_waiting > 0:
        raw_chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        for line in raw_chunk.split('\n'):
            line = line.strip()
            if "RAW:" in line:
                line = line.split("RAW:")[1].strip()
            try:
                samples.append(int(line))
            except ValueError:
                continue
    return samples

# Live plotting

plt.style.use('dark_background')
fig, (ax_filt, ax_metric) = plt.subplots(2, 1, figsize=(11, 7))
fig.canvas.manager.set_window_title('FP1 Debounced & Filtered Blink Monitor')

raw_buffer = np.zeros(PLOT_SAMPLES)
metric_buffer = np.zeros(METRIC_SAMPLES)

# Plot 1: Filtered Waveform
line_filt, = ax_filt.plot(np.zeros(PLOT_SAMPLES), color='#00ff66', lw=1.5, label='Filtered EOG (1-15 Hz)')
ax_filt.set_title('1. Filtered Signal (Biphasic Wave)')
ax_filt.set_ylabel('uV')
ax_filt.set_ylim(-150, 150)
ax_filt.legend(loc='upper right')
ax_filt.grid(True, alpha=0.2)

# Plot 2: Debounced Peak-to-Peak Amplitude
line_metric, = ax_metric.plot(metric_buffer, color='#ffcc00', lw=1.8, label='Debounced Peak Metric')
text_status = ax_metric.text(0.02, 0.85, "STATUS: READY", transform=ax_metric.transAxes, fontsize=12, fontweight='bold', color='#00ff66')


# Setting a threshold estimate
THRESHOLD = 300.0
line_thresh = ax_metric.axhline(THRESHOLD, color='#ff3366', linestyle='--', lw=1.5, label=f'Threshold ({THRESHOLD:.0f} uV)')

ax_metric.set_title('2. Debounced Amplitude Metric (Single Peak per Blink)')
ax_metric.set_ylabel('uV Swing')
ax_metric.set_ylim(0, 500)
ax_metric.legend(loc='upper right')
ax_metric.grid(True, alpha=0.2)

last_blink_time = [0]
DEBOUNCE_SEC = 0.35  # 350ms cooldown prevents double-peaking from biphasic rebound

def update(frame):
    pts = get_raw_samples()
    if not pts:
        return line_filt, line_metric, text_status

    for s in pts:
        raw_buffer[:-1] = raw_buffer[1:]
        raw_buffer[-1] = s

    detrended = raw_buffer - np.mean(raw_buffer)
    filtered = lfilter(b_bp, a_bp, detrended)

    # Active window swing
    recent_win = filtered[-WIN_LEN:]
    ptp_val = np.ptp(recent_win)

    # Measure width of the elevation (count samples > 50% of peak height)
    half_peak = np.max(recent_win) * 0.5
    peak_width_samples = np.sum(recent_win > half_peak)

    metric_buffer[:-1] = metric_buffer[1:]
    metric_buffer[-1] = ptp_val

    line_filt.set_ydata(filtered)
    line_metric.set_ydata(metric_buffer)

    now = time.time()
    
    # Check trigger conditions: Above threshold + Valid Width (>15 samples) + Debounced (>350ms)
    if ptp_val > THRESHOLD and peak_width_samples > 15 and (now - last_blink_time[0] > DEBOUNCE_SEC):
        play_sound(click_cue)
        text_status.set_text("single blink registered!")
        text_status.set_color('#00ff66')
        last_blink_time[0] = now
    elif ptp_val > THRESHOLD and (now - last_blink_time[0] <= DEBOUNCE_SEC):
        text_status.set_text("debouncing, rebound ignored.")
        text_status.set_color('#ffcc00')
    elif now - last_blink_time[0] > 0.6:
        text_status.set_text("ready!")
        text_status.set_color('#00e5ff')

    return line_filt, line_metric, text_status

ani = animation.FuncAnimation(fig, update, interval=30, blit=False, cache_frame_data=False)
plt.tight_layout()
plt.show()

ser.close()