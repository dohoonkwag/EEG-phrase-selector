import serial
import time
import subprocess
import os
import tempfile
import numpy as np
import asyncio
import edge_tts
import threading
from scipy.signal import butter, lfilter, lfilter_zi

PORT = '/dev/cu.usbmodem1101'
BAUD = 115200

FS = 512 
WIN_LEN = int(FS * 0.25)

# Adjustable!
THRESHOLD = 300.0          # Peak-to-Peak amplitude threshold (uV)
BLINK_LOCKOUT = 0.75       # Hard lockout window to prevent one blink counting as two
INTER_BLINK_TIMEOUT = 1.5  # Seconds allowed between blinks in a pattern sequence

# voices!
VOICE_EN = "en-US-GuyNeural"
VOICE_KO = "ko-KR-InJoonNeural"

# Demo script
PHRASES = [
    (
        "Hello everyone, my name is Doh-hoon Kwog, and this is my EOG phrase selector, a personal passion project of mine.", 
        "안녕하세요 여러분, 저는 곽도훈이라고 합니다. 지금 보시는 건 제가 개인적으로 정말 애정을 갖고 만든 프로젝트인 EOG 문구 선택기입니다"
    ),
    (
        "Isn’t it pretty cool? I am narrating this entire video without opening my mouth, using only my blinks.", 
        "꽤 멋지지 않나요? 저는 입을 한 번도 열지 않고, 오직 눈 깜빡임 만으로 이 영상을 설명하고 있어요."
    ),
    (
        "I built this project using the NeuroSky MindWave Mobile 2, which relies on a single dry electrode on my forehead. I blink twice to scroll through the options, and blink four times to have the computer speak the phrase that is currently selected.", 
        "이 프로젝트는 이마에 건식 전극 딱 하나만 붙이는 뉴로스카이 마인드웨이브 모바일 2를 사용해서 만들었습니다. 눈을 두 번 깜빡이면 선택지를 넘기고, 네 번 깜빡이면 해당 문구를 읽어줍니다."
    ),
    (
        "To decode these blinks, my script runs the raw EEG data through a bandpass filter to isolate the 1 to 15 Hertz range. It then calculates the peak-to-peak amplitude over a rolling window to detect massive voltage swings.", 
        "이 눈 깜빡임 신호를 인식하기 위해, 제가 만든 스크립트는 먼저 뇌파 데이터를 대역통과 필터에 통과시켜 1에서 15헤르츠 대역만 걸러냅니다. 그런 다음 이동 윈도우 방식으로 피크 간 진폭을 계산해서 큰 전압 변화를 잡아내는 거죠."
    ),
    (
        "One of the biggest challenges with this project was the hardware itself. I successfully connected to the headset via Bluetooth through an Arduino Uno and an HC-05 module, but because the MindWave Mobile 2 lacks recent developer support, modern documentation was incredibly hard to find.", 
        "이 프로젝트에서 가장 어려웠던 부분 중 하나는 하드웨어였어요. 아두이노 우노랑 HC-05 모듈을 써서 블루투스로 헤드셋 연결까지는 성공했지만, 마인드웨이브 모바일 2가 최근 개발자 지원이 거의 없다 보니 최신 문서를 찾기가 정말 어려웠습니다."
    ),
    (
        "In addition, I originally tried writing my own algorithms to calculate beta and alpha band power, rather than relying on the headset’s built-in metrics. However, separating cortical signals from muscle noise using just a single dry electrode on the FP1 position has proved to be a physiological wall that I haven't been able to cross yet.", 
        "처음에는 헤드셋에 내장된 지표를 그냥 쓰는 대신, 베타 및 알파 대역 파워를 직접 계산하는 알고리즘을 짜보려고 했어요. 그런데 FP1 위치에 놓인 건식 전극 하나만으로 대뇌피질 신호와 근육 잡음을 분리하는 건, 아직 제가 넘기 힘든 벽이었어요."
    ),
    (
        "So, I pivoted to EOG signals and wrote a custom debouncing algorithm to filter out false triggers.", 
        "그래서 방향을 틀어서 EOG 신호를 활용하기로 했고, 잘못된 입력을 걸러내기 위해 맞춤형 디바운싱 알고리즘을 만들었어요."
    ),
    (
        "Going forward, I'd like to explore better ways to filter noise so I can eventually use custom meditation metrics for control. Alternatively, I might build a custom headset with an electrode placed in a much better spot for pure EEG data.", 
        "앞으로는 잡음을 더 잘 걸러낼 방법을 찾아서, 언젠가는 제가 직접 만든 명상 지표로 프로그램을 제어해 보고 싶어요. 아니면 순수한 뇌파 데이터를 잘 측정할 수 있도록, 전극을 더 적절한 위치에 배치한 맞춤형 헤드셋을 직접 만들어볼 수도 있을 것 같습니다."
    ),
    (
        "If you want to see the code or learn more about the signal processing behind this, check out the project on my GitHub. Thanks for watching!", 
        "코드나 이 프로젝트에 쓰인 신호 처리 과정이 궁금하시다면 제 깃허브를 확인해 주세요. 시청해 주셔서 감사합니다!"
    )
]

# Block all blink detection while audio is playing
is_speaking = False

# 1-15 Hz Bandpass Filter for EOG Blinks
nyq = 0.5 * FS
b_bp, a_bp = butter(2, [1.0 / nyq, 15.0 / nyq], btype='band')

def make_cue(filename, freq_hz, duration_sec=0.12, volume=0.2):
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

# Sound Cues
blink_tick = make_cue("blink_tick.wav", 1200, 0.05, 0.15)    # Every blink
scroll_sound = make_cue("scroll_tone.wav", 600, 0.15, 0.25)   # Confirm double-blink
select_sound = make_cue("select_tone.wav", 900, 0.35, 0.3)    # Confirm 4-blink
discard_sound = make_cue("discard_tone.wav", 300, 0.1, 0.1)   # invalid pattern

def play_sound(filepath):
    subprocess.Popen(["afplay", filepath])

# speech
async def _speak_bilingual_async(en_text, ko_text):
    global is_speaking
    is_speaking = True
    
    file_en = os.path.join(tempfile.gettempdir(), "temp_en.mp3")
    file_ko = os.path.join(tempfile.gettempdir(), "temp_ko.mp3")
    
    try:
        comm_en = edge_tts.Communicate(en_text, VOICE_EN)
        await comm_en.save(file_en)
        
        comm_ko = edge_tts.Communicate(ko_text, VOICE_KO)
        await comm_ko.save(file_ko)
        
        subprocess.run(["afplay", file_en])
        time.sleep(0.2)
        subprocess.run(["afplay", file_ko])
    except Exception as e:
        print(f"TTS Error: {e}")
    finally:
        for f in (file_en, file_ko):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        # Unlock blink detection
        is_speaking = False

def speak_in_background(en_text, ko_text):
    def run_async():
        asyncio.run(_speak_bilingual_async(en_text, ko_text))
    threading.Thread(target=run_async, daemon=True).start()

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

def print_menu(current_idx, active_blinks=0):
    os.system('clear')
    print("EOG Phrase Selector!")
    print(f" Active Blink Pattern Sequence: [ {'• ' * active_blinks} ]")
    print("-" * 65 + "\n")
    
    for idx, (en, ko) in enumerate(PHRASES):
        if idx == current_idx:
            print(f"  ===> [ {idx + 1} ] {en.upper()} | {ko}  <===")
        else:
            print(f"       [ {idx + 1} ] {en} | {ko}")
    print("\n" + "=" * 65)



raw_buffer = np.zeros(FS * 2)
zi = lfilter_zi(b_bp, a_bp)

current_phrase_idx = 0
blink_count = 0
last_blink_time = 0
sequence_start_time = 0
lockout_until = 0

print_menu(current_phrase_idx, blink_count)

try:
    while True:
        pts = get_raw_samples()
        now = time.time()

        for s in pts:
            raw_buffer[:-1] = raw_buffer[1:]
            raw_buffer[-1] = s

        detrended = raw_buffer - np.mean(raw_buffer)
        filtered, _ = lfilter(b_bp, a_bp, detrended, zi=zi*detrended[0])

        recent_win = filtered[-WIN_LEN:]
        ptp_val = np.ptp(recent_win)

        half_peak = np.max(recent_win) * 0.5
        peak_width_samples = np.sum(recent_win > half_peak)

        # individual blinks
        if not is_speaking and now > lockout_until:
            if ptp_val > THRESHOLD and peak_width_samples > 15:
                play_sound(blink_tick)
                blink_count += 1
                
                last_blink_time = now
                sequence_start_time = now
                
                # Enforce lockout window
                lockout_until = now + BLINK_LOCKOUT
                
                # Flush arrays and re-init filter state
                raw_buffer.fill(0)
                zi = lfilter_zi(b_bp, a_bp)
                
                print_menu(current_phrase_idx, blink_count)

        # pattern sequence on timeout
        if not is_speaking and blink_count > 0 and (now - sequence_start_time > INTER_BLINK_TIMEOUT) and (now > lockout_until):
            if blink_count == 2:
                play_sound(scroll_sound)
                current_phrase_idx = (current_phrase_idx + 1) % len(PHRASES)
                print(f"\n scrolled to option {current_phrase_idx + 1}")

            elif blink_count == 4:
                play_sound(select_sound)
                en_text, ko_text = PHRASES[current_phrase_idx]
                print(f"\n selected and speaking! \n EN: '{en_text}'\n KO: '{ko_text}'")

                speak_in_background(en_text, ko_text)

            # invalid count
            else:
                play_sound(discard_sound)
                print(f"\n [ Discarded Pattern: {blink_count} blinks collected ]")

            # Reset
            blink_count = 0
            raw_buffer.fill(0)
            zi = lfilter_zi(b_bp, a_bp)
            ser.reset_input_buffer()
            
            print_menu(current_phrase_idx, blink_count)

        time.sleep(0.005)

except KeyboardInterrupt:
    print("\nPhrase selector stopped.")
finally:
    ser.close()