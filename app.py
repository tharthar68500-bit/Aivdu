import os
import subprocess
import tempfile
from pathlib import Path

import requests
import soundfile as sf
import streamlit as st
import whisper

from myanmar_tts import MyanmarTTS


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="Chinese → Myanmar AI Dubbing",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Chinese → Myanmar AI Auto-Dubbing")

st.write(
    "တရုတ် Drama Video ထည့်ပါ → "
    "တရုတ်စကားကို စာသားပြောင်း → "
    "မြန်မာလို ဘာသာပြန် → "
    "မြန်မာအသံပြန်သွင်း → MP4 ထုတ်"
)


# =========================================================
# SETTINGS
# =========================================================

st.sidebar.header("⚙️ Settings")

whisper_size = st.sidebar.selectbox(
    "Whisper Model",
    ["base", "small"],
    index=0,
)

keep_chinese = st.sidebar.checkbox(
    "မူရင်းတရုတ်အသံ အနည်းငယ်ထားမည်",
    value=False,
)

if keep_chinese:
    chinese_volume = st.sidebar.slider(
        "Chinese Original Volume",
        0.0,
        0.20,
        0.03,
        0.01,
    )
else:
    chinese_volume = 0.0


# =========================================================
# LOAD WHISPER
# =========================================================

@st.cache_resource
def load_whisper(model_name):
    return whisper.load_model(model_name)


# =========================================================
# LOAD MYANMAR TTS
# =========================================================

@st.cache_resource
def load_myanmar_tts():
    # CPU သုံးရန်
    return MyanmarTTS(device="cpu")


# =========================================================
# VIDEO DURATION
# =========================================================

def get_duration(video_path):

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        return float(result.stdout.strip())

    except Exception as e:

        st.error(
            f"Video duration မဖတ်နိုင်ပါ: {e}"
        )

        return 0


# =========================================================
# CHINESE → MYANMAR TRANSLATION
# =========================================================

def translate_to_myanmar(text):

    if not text.strip():
        return ""

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
        )

        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "my",
            "dt": "t",
            "q": text,
        }

        response = requests.get(
            url,
            params=params,
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        translated = ""

        for item in data[0]:

            if item and item[0]:
                translated += item[0]

        return translated.strip()

    except Exception as e:

        st.warning(
            f"ဘာသာပြန် Error: {e}"
        )

        return text


# =========================================================
# MYANMAR TTS
# =========================================================

def create_myanmar_voice(
    tts,
    text,
    output_path,
):

    try:

        audio = tts.tts(
            text,
            solver="euler",
            step=12,
            cfg=3.0,
        )

        sf.write(
            str(output_path),
            audio,
            44100,
        )

        return True

    except Exception as e:

        st.error(
            f"Myanmar TTS Error: {e}"
        )

        return False


# =========================================================
# GET AUDIO DURATION
# =========================================================

def get_audio_duration(audio_path):

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        return float(
            result.stdout.strip()
        )

    except:

        return 0


# =========================================================
# FIT TTS AUDIO TO ORIGINAL DIALOGUE TIME
# =========================================================

def fit_audio(
    input_audio,
    output_audio,
    target_duration,
):

    current_duration = get_audio_duration(
        input_audio
    )

    if current_duration <= 0:
        return False

    if target_duration <= 0:
        return False

    ratio = (
        current_duration /
        target_duration
    )

    filters = []

    while ratio > 2.0:

        filters.append(
            "atempo=2.0"
        )

        ratio /= 2.0

    while ratio < 0.5:

        filters.append(
            "atempo=0.5"
        )

        ratio /= 0.5

    if abs(ratio - 1.0) > 0.01:

        filters.append(
            f"atempo={ratio:.4f}"
        )

    if not filters:
        filters.append("anull")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_audio),
        "-filter:a",
        ",".join(filters),
        "-t",
        str(target_duration),
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output_audio),
    ]

    try:

        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        return True

    except Exception:

        return False


# =========================================================
# CREATE SILENCE
# =========================================================

def create_silence(
    output_file,
    duration,
):

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:"
        "sample_rate=44100",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",
        str(output_file),
    ]

    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


# =========================================================
# CREATE TIMED DUBBING TRACK
# =========================================================

def create_dubbing_track(
    video_duration,
    segments,
    output_audio,
):

    if not segments:
        return False

    temp_dir = output_audio.parent

    silence_file = (
        temp_dir /
        "silence.wav"
    )

    create_silence(
        silence_file,
        video_duration,
    )

    inputs = [
        "-i",
        str(silence_file),
    ]

    filters = [
        "[0:a]anull[base]"
    ]

    for index, segment in enumerate(
        segments
    ):

        inputs.extend([
            "-i",
            str(segment["file"]),
        ])

        delay = int(
            segment["start"] * 1000
        )

        filters.append(
            f"[{index + 1}:a]"
            f"adelay={delay}|{delay}"
            f"[a{index}]"
        )

    mix = "[base]"

    for index in range(
        len(segments)
    ):
        mix += f"[a{index}]"

    filters.append(
        f"{mix}"
        f"amix="
        f"inputs={len(segments) + 1}:"
        f"duration=first:"
        f"dropout_transition=0"
        f"[out]"
    )

    command = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(video_duration),
        str(output_audio),
    ]

    try:

        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )

        return True

    except subprocess.CalledProcessError as e:

        st.error(
            "Dubbing track Error:\n"
            + e.stderr.decode(
                errors="ignore"
            )[-2000:]
        )

        return False


# =========================================================
# CREATE FINAL VIDEO
# =========================================================

def create_final_video(
    original_video,
    dubbing_audio,
    output_video,
):

    if keep_chinese:

        filter_complex = (
            f"[0:a]volume={chinese_volume}"
            "[original];"
            "[1:a]volume=1.0[dub];"
            "[original][dub]"
            "amix=inputs=2:"
            "duration=first:"
            "dropout_transition=0"
            "[audio]"
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(original_video),
            "-i",
            str(dubbing_audio),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[audio]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_video),
        ]

    else:

        # IMPORTANT:
        # Chinese original audio is removed.
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(original_video),
            "-i",
            str(dubbing_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_video),
        ]

    try:

        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )

        return True

    except subprocess.CalledProcessError as e:

        st.error(
            e.stderr.decode(
                errors="ignore"
            )[-3000:]
        )

        return False


# =========================================================
# VIDEO UPLOAD
# =========================================================

st.subheader(
    "📹 တရုတ် Drama Video ထည့်ပါ"
)

video_file = st.file_uploader(
    "MP4 / MOV / MKV",
    type=[
        "mp4",
        "mov",
        "mkv",
    ],
)


# =========================================================
# START
# =========================================================

if st.button(
    "🚀 မြန်မာ Dubbing စတင်မည်",
    type="primary",
):

    if video_file is None:

        st.warning(
            "⚠️ Video အရင်ထည့်ပါ။"
        )

        st.stop()

    work_dir = Path(
        tempfile.mkdtemp(
            prefix="mm_dub_"
        )
    )

    try:

        # ---------------------------------------------
        # SAVE VIDEO
        # ---------------------------------------------

        input_video = (
            work_dir /
            "input.mp4"
        )

        with open(
            input_video,
            "wb",
        ) as f:

            f.write(
                video_file.getbuffer()
            )

        duration = get_duration(
            input_video
        )

        if duration <= 0:

            st.error(
                "❌ Video မဖတ်နိုင်ပါ။"
            )

            st.stop()

        if duration > 600:

            st.error(
                "❌ 10 မိနစ်ထက် မကျော်ရပါ။"
            )

            st.stop()

        st.success(
            f"Video Duration: "
            f"{duration:.2f} seconds"
        )


        # ---------------------------------------------
        # LOAD AI
        # ---------------------------------------------

        with st.spinner(
            "🧠 Whisper AI ဖွင့်နေပါသည်..."
        ):

            whisper_model = load_whisper(
                whisper_size
            )

        with st.spinner(
            "🇲🇲 Myanmar TTS ဖွင့်နေပါသည်..."
        ):

            myanmar_tts = (
                load_myanmar_tts()
            )


        # ---------------------------------------------
        # WHISPER
        # ---------------------------------------------

        with st.spinner(
            "🎧 တရုတ်စကားကို ဖတ်နေပါသည်..."
        ):

            result = whisper_model.transcribe(
                str(input_video),
                language="zh",
                task="transcribe",
                fp16=False,
                verbose=False,
            )

        segments = result.get(
            "segments",
            []
        )

        if not segments:

            st.error(
                "❌ တရုတ်စကားပြော မတွေ့ပါ။"
            )

            st.stop()

        st.success(
            f"📝 Dialogue "
            f"{len(segments)} ခု တွေ့ပါသည်။"
        )


        # ---------------------------------------------
        # TRANSLATE + TTS
        # ---------------------------------------------

        dubbing_segments = []

        progress = st.progress(0)

        for index, segment in enumerate(
            segments
        ):

            chinese_text = segment.get(
                "text",
                ""
            ).strip()

            start = float(
                segment.get(
                    "start",
                    0
                )
            )

            end = float(
                segment.get(
                    "end",
                    start
                )
            )

            target_duration = (
                end - start
            )

            if not chinese_text:
                continue

            if target_duration <= 0:
                continue

            st.markdown(
                f"### #{index + 1}"
            )

            st.write(
                f"⏱️ "
                f"{start:.2f}s → "
                f"{end:.2f}s"
            )

            st.write(
                f"🇨🇳 {chinese_text}"
            )


            # -----------------------------------------
            # TRANSLATION
            # -----------------------------------------

            myanmar_text = (
                translate_to_myanmar(
                    chinese_text
                )
            )

            st.write(
                f"🇲🇲 {myanmar_text}"
            )

            if not myanmar_text:
                continue


            # -----------------------------------------
            # TTS
            # -----------------------------------------

            raw_audio = (
                work_dir /
                f"raw_{index}.wav"
            )

            fitted_audio = (
                work_dir /
                f"fit_{index}.wav"
            )

            with st.spinner(
                f"🎙️ Myanmar အသံ "
                f"#{index + 1} ထုတ်နေပါသည်..."
            ):

                created = (
                    create_myanmar_voice(
                        myanmar_tts,
                        myanmar_text,
                        raw_audio,
                    )
                )

            if not created:
                continue


            # -----------------------------------------
            # FIT TIMING
            # -----------------------------------------

            fitted = fit_audio(
                raw_audio,
                fitted_audio,
                target_duration,
            )

            if not fitted:
                continue

            dubbing_segments.append(
                {
                    "file": fitted_audio,
                    "start": start,
                    "end": end,
                }
            )

            progress.progress(
                min(
                    1.0,
                    (index + 1)
                    / len(segments)
                )
            )


        # ---------------------------------------------
        # CHECK
        # ---------------------------------------------

        if not dubbing_segments:

            st.error(
                "❌ Myanmar အသံ ထုတ်၍မရပါ။"
            )

            st.stop()


        # ---------------------------------------------
        # BUILD DUB AUDIO
        # ---------------------------------------------

        st.info(
            "🎚️ Myanmar အသံတွေကို "
            "မူရင်း timing အတိုင်း တည်နေပါသည်..."
        )

        dubbing_audio = (
            work_dir /
            "myanmar_dubbing.m4a"
        )

        created = create_dubbing_track(
            duration,
            dubbing_segments,
            dubbing_audio,
        )

        if not created:

            st.error(
                "❌ Dubbing audio မတည်နိုင်ပါ။"
            )

            st.stop()


        # ---------------------------------------------
        # FINAL VIDEO
        # ---------------------------------------------

        st.info(
            "🎬 Final Video ပြုလုပ်နေပါသည်..."
        )

        final_video = (
            work_dir /
            "Myanmar_Dubbed_Final.mp4"
        )

        created = create_final_video(
            input_video,
            dubbing_audio,
            final_video,
        )

        if not created:

            st.error(
                "❌ Final Video မထွက်ပါ။"
            )

            st.stop()


        # ---------------------------------------------
        # RESULT
        # ---------------------------------------------

        st.success(
            "🎉 မြန်မာ Dubbing အောင်မြင်ပါပြီ!"
        )

        st.video(
            str(final_video)
        )

        with open(
            final_video,
            "rb"
        ) as f:

            st.download_button(
                "📥 Myanmar Dubbed Video Download",
                data=f,
                file_name=(
                    "Myanmar_Dubbed_Final.mp4"
                ),
                mime="video/mp4",
            )

    except Exception as e:

        st.error(
            f"❌ Error: {e}"
        )