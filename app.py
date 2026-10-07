import math
import os
import re
import subprocess
import cv2
import numpy as np
import requests
import streamlit as st

# Streamlit UI Configuration
st.set_page_config(
    page_title="AI Batch Video Dubbing & Blur App",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 AI Multi-Video Batch Dubbing & Processing System")
st.write(
    "ဗီဒီယို (၃) ပုဒ် အလိုအလျောက် Dubbing ပြုလုပ်ခြင်း၊ အသံခွဲခြားခြင်း၊ ဘာသာစကားရွေးချယ်ခြင်း၊ ၁၀ မိနစ် ကန့်သတ်ချက် နှင့် စာသား Blur ပြုလုပ်နိုင်သော စနစ်"
)

# Sidebar Options
st.sidebar.header("⚙️ အခြေခံ ဆက်တင်များ")
api_key = st.sidebar.text_input("ElevenLabs API Key ထည့်ပါ", type="password")

# ဘာသာစကား ရွေးချယ်နိုင်သော စနစ် (Language Selection)
LANGUAGES = {
    "မြန်မာ (Myanmar)": "my",
    "အင်္ဂလိပ် (English)": "en",
    "တရုတ် (Chinese)": "zh",
    "ဂျပန် (Japanese)": "ja",
    "ကိုရီးယား (Korean)": "ko",
    "ထိုင်း (Thai)": "th",
}
selected_lang = st.sidebar.selectbox("🌐 ထွက်ရှိလာမည့် ဘာသာစကား ရွေးပါ", list(LANGUAGES.keys()))

# ဇာတ်ကောင် အသံ ရွေးချယ်မှုများ
VOICE_MALE = {"Adam (အမျိုးသား)": "2EiwWnXFnvU5JabPnv8n"}
VOICE_FEMALE = {"Rachel (အမျိုးသမီး)": "21m00Tcm4TlvDq8ikWAM"}

male_voice_id = VOICE_MALE["Adam (အမျိုးသား)"]
female_voice_id = VOICE_FEMALE["Rachel (အမျိုးသမီး)"]


# ၁၀ မိနစ် ကန့်သတ်ချက် စစ်ဆေးသည့် Function
def get_video_duration(video_path):
    try:
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        output = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        return float(output)
    except Exception as e:
        st.error(f"ဗီဒီယို ကြာမြင့်ချိန် စစ်ဆေး၍ မရပါ: {e}")
        return 0.0


# ElevenLabs မှ ဘာသာစကားအလိုက် အသံ ထုတ်ယူသည့် Function
def generate_ai_voice(text, voice_id, key):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": key,
    }
    data = {
        "text": text,
        # Multi-language စနစ်အတွက် eleven_multilingual_v2 ကို အသုံးပြုသည်
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.35, "similarity_boost": 0.75},
    }
    res = requests.post(url, json=data, headers=headers)
    if res.status_code == 200:
        return res.content
    return None


# စာသားဝါးခြင်း (Subtitles Blur) Function - OpenCV အသုံးပြု၍
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
        # ရွေးချယ်ထားသော စာသားနေရာကို Gaussian Blur ပေးခြင်း
        if y2 > y1 and y1 >= 0 and y2 <= height:
            roi = frame[y1:y2, 0:width]
            blurred_roi = cv2.GaussianBlur(roi, (51, 51), 30)
            frame[y1:y2, 0:width] = blurred_roi
        out.write(frame)

    cap.release()
    out.release()

    # မူရင်း ဗီဒီယို၏ Audio ကို ပြန်လည် ပေါင်းစပ်ခြင်း
    merge_cmd = f'ffmpeg -y -i "{temp_blur_video}" -i "{input_path}" -c:v copy -c:a copy -map 0:v:0 -map 1:a:0? "{output_path}"'
    subprocess.run(merge_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(temp_blur_video):
        os.remove(temp_blur_video)


# MAIN UI SECTION
st.subheader("၁။ ဗီဒီယို (၃) ပုဒ် တင်ပါ (အများဆုံး ၁၀ မိနစ်အထိ)")
col1, col2, col3 = st.columns(3)

with col1:
    v1 = st.file_uploader("ဗီဒီယို (၁)", type=["mp4", "mov"], key="v1")
    txt1 = st.text_area("ဗီဒီယို ၁ အတွက် စာသား", placeholder="[Adam]: မင်း ဘာလုပ်နေတာလဲ!\n[Rachel]: [crying] ငါမသိဘူး...", key="t1")

with col2:
    v2 = st.file_uploader("ဗီဒီယို (၂)", type=["mp4", "mov"], key="v2")
    txt2 = st.text_area("ဗီဒီယို ၂ အတွက် စာသား", placeholder="[Adam]: [shouts] ထွက်သွား!", key="t2")

with col3:
    v3 = st.file_uploader("ဗီဒီယို (၃)", type=["mp4", "mov"], key="v3")
    txt3 = st.text_area("ဗီဒီယို ၃ အတွက် စာသား", placeholder="[Rachel]: [giggles] ရယ်စရာပဲ...", key="t3")

st.markdown("---")
st.subheader("၂။ စာသား ဝါးရန် (Subtitles Blur) ဆက်တင်များ")
enable_blur = st.checkbox("ထွက်လာမည့် ဗီဒီယိုတွင် အောက်ခြေ စာသားများကို ဝါးမည် (Blur)", value=False)

blur_y = 80
blur_h = 15
if enable_blur:
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        blur_y = st.slider("Blur ပြုလုပ်မည့် အမြင့် နေရာ (%)", 0, 100, 80)
    with b_col2:
        blur_h = st.slider("Blur ပြုလုပ်မည့် အနံ/အထူ (%)", 5, 30, 15)

st.markdown("---")

if st.button("🚀 ဗီဒီယို (၃) ပုဒ် အလိုအလျောက် စတင် Processing လုပ်မည်"):
    videos_to_process = [(v1, txt1, "Video_1"), (v2, txt2, "Video_2"), (v3, txt3, "Video_3")]

    if not api_key:
        st.warning("⚠️ ကျေးဇူးပြု၍ ElevenLabs API Key ကို ရေးထည့်ပါ!")
    else:
        for idx, (v_file, txt, name) in enumerate(videos_to_process):
            if v_file is not None:
                st.info(f"🔄 {name} ကို စတင် လုပ်ဆောင်နေပါသည်... (ရွေးချယ်ထားသော ဘာသာစကား: {selected_lang})")

                raw_path = f"raw_{name}.mp4"
                with open(raw_path, "wb") as f:
                    f.write(v_file.getbuffer())

                # ကြာမြင့်ချိန် စစ်ဆေးခြင်း (၁၀ မိနစ် = ၆၀၀ စက္ကန့်)
                duration = get_video_duration(raw_path)
                if duration > 600:
                    st.error(f"❌ {name} သည် ၁၀ မိနစ်ထက် ကျော်လွန်နေပါသည် (ကြာမြင့်ချိန်: {round(duration/60, 2)} မိနစ်)။ လုပ်ဆောင်ခွင့် မရှိပါ။")
                    continue

                # Audio Generation & Separation
                final_audio_list = []
                lines = txt.split("\n")
                for l_idx, line in enumerate(lines):
                    line = line.strip()
                    if not line:
                        continue

                    # အမျိုးသား/အမျိုးသမီး အသံ ခွဲခြားခြင်း
                    target_voice = male_voice_id
                    clean_text = line

                    if line.startswith("[Rachel]") or line.startswith("[Female]"):
                        target_voice = female_voice_id
                        clean_text = re.sub(r"^\[.*?\]", "", line).strip()
                    elif line.startswith("[Adam]") or line.startswith("[Male]"):
                        target_voice = male_voice_id
                        clean_text = re.sub(r"^\[.*?\]", "", line).strip()

                    a_bytes = generate_ai_voice(clean_text, target_voice, api_key)
                    if a_bytes:
                        part_file = f"audio_{name}_{l_idx}.mp3"
                        with open(part_file, "wb") as pf:
                            pf.write(a_bytes)
                        final_audio_list.append(part_file)

                # FFmpeg ဖြင့် မူရင်း ဗီဒီယို + မူရင်း BGM + AI Dubbing Voice ပေါင်းစပ်ခြင်း
                dubbed_output = f"dubbed_{name}.mp4"
                if final_audio_list:
                    # အသံဖိုင်များကို တစ်ဆက်တည်း ပေါင်းခြင်း
                    concat_list_file = f"concat_{name}.txt"
                    with open(concat_list_file, "w") as cf:
                        for af in final_audio_list:
                            cf.write(f"file '{af}'\n")

                    merged_ai_voice = f"full_ai_voice_{name}.mp3"
                    subprocess.run(f'ffmpeg -y -f concat -safe 0 -i {concat_list_file} -c copy {merged_ai_voice}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                    # မူရင်း ဗီဒီယို နောက်ခံအသံ (BGM) ပါဝင်စေပြီး AI အသံဖြင့် ထပ်ပေါင်းခြင်း (amix)
                    mix_cmd = f'ffmpeg -y -i "{raw_path}" -i "{merged_ai_voice}" -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[a]" -map 0:v -map "[a]" -c:v copy "{dubbed_output}"'
                    subprocess.run(mix_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    dubbed_output = raw_path

                # စာသား ဝါးခြင်း (Blur) စနစ် ဆက်လက် လုပ်ဆောင်ခြင်း
                final_result_path = f"Final_{name}.mp4"
                if enable_blur:
                    apply_blur_to_video(dubbed_output, final_result_path, blur_y, blur_h)
                else:
                    final_result_path = dubbed_output

                # 安全 Check ဖြင့် Output ဖိုင်ရှိမှ ပြသခြင်း
                if final_result_path and os.path.exists(final_result_path):
                    st.success(f"✅ {name} Dubbing & Processing အောင်မြင်စွာ ပြီးဆုံးပါပြီ!")
                    st.video(final_result_path)

                    # Download Button ပြသခြင်း
                    with open(final_result_path, "rb") as file:
                        st.download_button(
                            label=f"📥 {name} ရလဒ် ဒေါင်းလုဒ်ဆွဲရန်",
                            data=file,
                            file_name=f"Processed_{name}.mp4",
                            mime="video/mp4",
                        )
                else:
                    st.error(f"⚠️ {name} ဗီဒီယို ဖိုင်မထွက်လာပါ သို့မဟုတ် လမ်းကြောင်း အဆင်မပြေပါ: {final_result_path}")
