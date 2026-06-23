import serial
import matplotlib.pyplot as plt
import numpy as np

arduino_port = '/dev/cu.usbmodem1101'  
baud_rate = 115200
sweep_seconds = 5
sample_rate = 512  # MindWave Mobile 2 native frequency
total_points = sample_rate * sweep_seconds

# Connect to USB serial
try:
    ser = serial.Serial(arduino_port, baud_rate, timeout=0.1)
except Exception as e:
    print(f"Error: {e}.\nMake sure the Arduino IDE Serial Monitor or Plotter is completely closed!")
    exit()

# Initialize a fixed array for the sweeping line
x_data = np.arange(total_points)
y_data = np.zeros(total_points)
y_data[:] = np.nan  # Clear with NaN so un-swept trailing points don't connect visually

# dark mode ayyyy
plt.ion()
fig, ax = plt.subplots(figsize=(12, 5))
line, = ax.plot(x_data, y_data, color='#00FFCC', linewidth=1.2)

fig.patch.set_facecolor('#111111')
ax.set_facecolor('#111111')
ax.set_xlim(0, total_points)
ax.set_ylim(-1200, 1200) 
ax.set_title("BCI Raw EEG Radar Sweep (5-Second Window)", color='white', fontsize=14)
ax.get_xaxis().set_visible(False)
ax.grid(True, color='#222222', linestyle='--')
ax.tick_params(colors='white')

print("Pipeline active! Put on the headset and watch the canvas sweep...")

write_index = 0

try:
    while True:
        if ser.in_waiting:
            raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
            if raw_line:
                try:
                    val = int(raw_line)
                    
                    # Update sweeping cursor position
                    y_data[write_index] = val
                    
                    # Create a trailing blanking gap right in front of the cursor
                    # This prevents the old data from blending with the fresh data
                    gap_size = 40
                    for g in range(1, gap_size):
                        y_data[(write_index + g) % total_points] = np.nan
                    
                    write_index += 1
                    
                    # Wrap back to the left side when we hit the edge
                    if write_index >= total_points:
                        write_index = 0
                        
                except ValueError:
                    continue
        
        # Redraw every 16 samples
        if write_index % 16 == 0:  
            line.set_ydata(y_data)
            fig.canvas.draw()
            fig.canvas.flush_events()

except KeyboardInterrupt:
    print("\nStream stopped gracefully.")
finally:
    ser.close()