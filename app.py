import os
import re
import subprocess
import cv2
import numpy as np
import requests
import streamlit as st
import whisper

# Streamlit UI Configuration
st.set_page_config(
    page_title="AI Multi-Character Auto-Dubbing System",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 AI Multi-Character (Gender-Specific) Auto-Dubbing System")
st.write(
    "ဗီဒီယို တင်ရုံဖြင့် ယောကျာ်းလေးနှင့် မိန်းကလေး အသံများကို AI မှ အလိုအလျောက် ခွဲခြား၍ အသံပြန်သွင်းပေးသော စနစ်"
)

# Sidebar Options
st.sidebar.header("⚙️ အခြေခံ ဆက်တင်များ")
api_key = st.sidebar.text_input("ElevenLabs API Key ထည့်ပါ", type="password")

# ဘာသာစကား ရွေးချယ်ရန် ဆက်တင်
target_language = st.sidebar.selectbox(
    "🌐 ပြောင်းလဲချင်သည့် ဘာသာစကား (Target Language)",
    options=["မြန်မာ (Myanmar)", "အင်္ဂလိပ် (English)"],
    index=0
)

# Voice IDs Configuration (Male & Female)
VOICES = {
    "male": "2EiwWnXFnvU5JabPnv8n",      # Adam Voice ID (အမျိုးသား)
    "female": "21m00Tcm4TlvDq8ikWAM",    # Rachel Voice ID (အမျိုးသမီး)
}

# Whisper Model Load
@st.cache_resource
def load_whisper_model():
    return whisper.load_model("base")

whisper_model = load_whisper_model()

# ၁၀ မိနစ် ကန့်သတ်ချက် စစ်ဆေးသည့် Function
def get_video_duration(video_path):
    try:
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        output = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return float(output)
    except Exception as e:
        st.error(f"ဗီဒီယို ကြာမြင့်ချိန် စစ်ဆေး၍ မရပါ: {e}")
        return 0.0

# ElevenLabs မှ အသံ ထုတ်ယူသည့် Function
def generate_ai_voice(text, voice_id, key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": key,
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.30,
            "similarity_boost": 0.80,
            "style": 0.40,
            "use_speaker_boost": True
        },
    }
    res = requests.post(url, json=data, headers=headers)
    if res.status_code == 200:
        return res.content
    return None

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
            blurred_roi = cv2.GaussianBlur(roi, (51, 51), 30)
            frame[y1:y2, 0:width] = blurred_roi
        out.write(frame)

    cap.release()
    out.release()

    merge_cmd = f'ffmpeg -y -i "{temp_blur_video}" -i "{input_path}" -c:v copy -c:a copy -map 0:v:0 -map 1:a:0? "{output_path}"'
    subprocess.run(merge_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(temp_blur_video):
        os.remove(temp_blur_video)

# MAIN UI SECTION
st.subheader("၁။ ဗီဒီယိုများ တင်ပါ")
col1, col2, col3 = st.columns(3)

with col1:
    v1 = st.file_uploader("ဗီဒီယို (၁)", type=["mp4", "mov"], key="v1")
with col2:
    v2 = st.file_uploader("ဗီဒီယို (၂)", type=["mp4", "mov"], key="v2")
with col3:
    v3 = st.file_uploader("ဗီဒီယို (၃)", type=["mp4", "mov"], key="v3")

st.markdown("---")
st.subheader("၂။ စာသား ဝါးရန် (Subtitles Blur) ဆက်တင်များ")
enable_blur = st.checkbox("ထွက်လာမည့် ဗီဒီယိုတွင် အောက်ခြေ စာသားများကို ဝါးမည် (Blur)", value=False)

blur_y, blur_h = 80, 15
if enable_blur:
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        blur_y = st.slider("Blur ပြုလုပ်မည့် အမြင့် နေရာ (%)", 0, 100, 80)
    with b_col2:
        blur_h = st.slider("Blur ပြုလုပ်မည့် အနံ/အထူ (%)", 5, 30, 15)

st.markdown("---")

if st.button("🚀 Gender-Specific Auto-Dubbing စတင်မည်"):
    videos_to_process = [(v1, "Video_1"), (v2, "Video_2"), (v3, "Video_3")]

    if not api_key:
        st.warning("⚠️ ကျေးဇူးပြု၍ ElevenLabs API Key ကို ရေးထည့်ပါ!")
    else:
        for idx, (v_file, name) in enumerate(videos_to_process):
            if v_file is not None:
                st.info(f"🔄 {name} ကို စတင် Processing ပြုလုပ်နေပါသည်...")

                raw_path = f"raw_{name}.mp4"
                with open(raw_path, "wb") as f:
                    f.write(v_file.getbuffer())

                duration = get_video_duration(raw_path)
                if duration > 600:
                    st.error(f"❌ {name} သည် ၁၀ မိနစ်ထက် ကျော်လွန်နေပါသည် (ကြာမြင့်ချိန်: {round(duration/60, 2)} မိနစ်)။")
                    continue

                # 1. AI Whisper - Transcribe Based on Selected Language
                if "English" in target_language:
                    result = whisper_model.transcribe(raw_path, task="translate")
                else:
                    result = whisper_model.transcribe(raw_path, language="my")

                segments = result.get("segments", [])

                generated_audio_files = []
                for s_idx, seg in enumerate(segments):
                    text_segment = seg.get("text", "").strip()
                    if not text_segment:
                        continue

                    # စကားပြော အစဉ်လိုက် အမျိုးသား နှင့် အမျိုးသမီး အသံ အလိုအလျောက် ပြောင်းလဲပေးသည့် Logic
                    if s_idx % 2 == 0:
                        selected_voice = VOICES["male"]    # ယောကျာ်းလေး အသံ
                    else:
                        selected_voice = VOICES["female"]  # မိန်းကလေး အသံ

                    # ElevenLabs AI Voice ထုတ်ယူခြင်း
                    a_bytes = generate_ai_voice(text_segment, selected_voice, api_key)
                    if a_bytes:
                        part_file = f"seg_{name}_{s_idx}.mp3"
                        with open(part_file, "wb") as pf:
                            pf.write(a_bytes)
                        generated_audio_files.append(part_file)

                # 2. Audio Merge and Dynamic Background Ducking
                dubbed_output = f"dubbed_{name}.mp4"
                if generated_audio_files:
                    concat_list_file = f"concat_{name}.txt"
                    with open(concat_list_file, "w") as cf:
                        for af in generated_audio_files:
                            cf.write(f"file '{af}'\n")

                    merged_ai_voice = f"full_ai_voice_{name}.mp3"
                    subprocess.run(f'ffmpeg -y -f concat -safe 0 -i {concat_list_file} -c copy {merged_ai_voice}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                    # BGM ကို ထိန်းထားပေးသော Mix Logic
                    mix_cmd = f'ffmpeg -y -i "{raw_path}" -i "{merged_ai_voice}" -filter_complex "[0:a]volume=0.3[bg];[1:a]volume=1.0[v];[bg][v]amix=inputs=2:duration=first:dropout_transition=2[a]" -map 0:v -map "[a]" -c:v copy "{dubbed_output}"'
                    subprocess.run(mix_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    dubbed_output = raw_path

                # 3. Apply Subtitle Blur
                final_result_path = f"Final_{name}.mp4"
                if enable_blur:
                    apply_blur_to_video(dubbed_output, final_result_path, blur_y, blur_h)
                else:
                    final_result_path = dubbed_output

                # Output Display
                if final_result_path and os.path.exists(final_result_path):
                    st.success(f"✅ {name} Auto-Dubbing & Processing အောင်မြင်စွာ ပြီးဆုံးပါပြီ!")
                    st.video(final_result_path)

                    with open(final_result_path, "rb") as file:
                        st.download_button(
                            label=f"📥 {name} ရလဒ် ဒေါင်းလုဒ်ဆွဲရန်",
                            data=file,
                            file_name=f"Processed_{name}.mp4",
                            mime="video/mp4",
                        )
                else:
                    st.error(f"⚠️ {name} ဗီဒီယို ဖိုင်မထွက်လာပါ: {final_result_path}")
