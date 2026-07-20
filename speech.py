# /opt/homebrew/bin/python3 -m pip install edge-tts --break-system-packagess

import asyncio
import edge_tts
import os

VOICE_EN = "en-US-GuyNeural"    # Male English Voice (or "en-US-ChristopherNeural")
VOICE_KO = "ko-KR-InJoonNeural" # Male Korean Voice

async def speak_async(text, voice):
    filename = "temp_speech.mp3"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)
    
    # Play using macOS built-in afplay
    os.system(f"afplay {filename}")
    
    if os.path.exists(filename):
        os.remove(filename)

def speak(text, voice):
    asyncio.run(speak_async(text, voice))

# lets try
print("Speaking English!")
speak("Hello, let me tell you about my passion project.", VOICE_EN)

print("Speaking Korean!")
speak("안녕하세요, 제가 열정을 쏟고 있는 프로젝트에 대해 말씀드리겠습니다.", VOICE_KO)