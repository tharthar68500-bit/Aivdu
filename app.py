import os
import re
import subprocess
import asyncio
import cv2
import numpy as np
import requests
import streamlit as st
import whisper
import edge_tts
from pydub import AudioSegment

# Streamlit UI Configuration
st.set_page_config(
    page_title="AI Multi-Character Auto-Dubbing System",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 AI Multi-Character (Gender-Specific) Auto-Dubbing System")
st.write(
    "ဗီဒီယို တင်ရုံဖြင့် တရုတ်/အခြားစကားပြောများကို မြန်မာစာ ဘာသာပြန်ပေးပြီး၊ ယောက်ျားလေး/မိန်းကလေး အသံများဖြင့် မူရင်း BGM မပျောက်ဘဲ အော်တို ဒပ်ဘင်း လုပ်ပေးသော စနစ်"
)

# Voice Configurations (Microsoft Edge TTS Myanmar Voices)
MYANMAR_VOICES = {
    "male": "my-MM-ThihaNeural",     # မြန်မာ အမျိုးသား အသံ
    "female": "my-MM-NilarNeural"    # မြန်မာ အမျိုးသမီး အသံ
}

# Whisper Model Load
@st.cache_resource
def load_whisper_model():
    return whisper.load_model("base")

whisper_model = load_whisper_model()

# ဗီဒီယို ကြာမြင့်ချိန် စစ်ဆေးသည့် Function
def get_video_duration(video_path):
    try:
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        output = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return float(output)
    except Exception as e:
        st.error(f"ဗီဒီယို ကြာမြင့်ချိန် စစ်ဆေး၍ မရပါ: {e}")
        return 0.0

# Free Google Translate Engine (To Myanmar)
def translate_to_myanmar(text):
    if not text.strip():
        return ""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=my&dt=t&q={requests.utils.quote(text)}"
        res = requests.get(url, timeout=10).json()
        translated_text = "".join([sentence[0] for sentence in res[0] if sentence[0]])
        return translated_text
    except Exception:
        return text

# Async Function for Edge-TTS Generation
async def generate_myanmar_voice_async(text, voice_name, output_file):
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_file)

def generate_myanmar_voice(text, voice_name, output_file):
    try:
        asyncio.run(generate_myanmar_voice_async(text, voice_name, output_file))
        return True
    except Exception as e:
        st.write(f"Voice gen error: {e}")
        return False

# Subtitles Blur Function
def apply_blur_to_video(input_path, output_path, blur_y, blur_h):
    cap = cv2.VideoCapture(input_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps == 0 or np.isnan(fps):
        fps = 25.0

    temp_blur_video = "temp_blurred_no_audio.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(temp_blur_video, fourcc, fps, (width, height))

    y1 = int(height * (blur_y / 100.0))
    y2 = int(height * ((blur_y + blur_h) / 100.0))

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if y2 > y1 and y1 >= 0 and y2 <= height:
            roi = frame[y1:y2, 0:width]
            blurred_roi = cv2.GaussianBlur(roi, (51, 
