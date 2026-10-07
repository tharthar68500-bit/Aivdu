import os
import time
import tempfile
import subprocess
from pathlib import Path

import streamlit as st
import requests
import torch
import soundfile as sf
import whisper

from huggingface_hub import hf_hub_download
from api import StableTTSAPI
from burmese import burmese_to_ipa2


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="AI Myanmar Drama Dubbing",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 AI Myanmar Drama Auto Dubbing")
st.caption(
    "Chinese Video → Whisper → Myanmar Translation → Myanmar Voice → Final MP4"
)


# =========================================================
# FUNCTIONS
# =========================================================

@st.cache_resource
def load_whisper():
    """
    Whisper model
    """
    return whisper.load_model("base")


@st.cache_resource
def load_myanmar_tts():

    device = "cuda" if torch.cuda.is_available() else "cpu"

    st.info(
        f"🇲🇲 Myanmar TTS model ကို {device.upper()} နဲ့ ဖွင့်နေပါတယ်..."
    )

    # CPU မှာ fp32 သုံး
    # GPU ရှိရင် fp16 သုံးနိုင်
    if device == "cuda":
        model_file = "model_fp16.pt"
    else:
        model_file = "model_fp32.pt"

    model_path = hf_hub_download(
        repo_id="freococo/MyanmarTTS",
        filename=model_file
    )

    vocos_path = hf_hub_download(
        repo_id="freococo/MyanmarTTS",
        filename="vocos.pt"
    )

    ref_path = hf_hub_download(
        repo_id="freococo/MyanmarTTS",
        filename="samples/sample_0.wav"
    )

    model = StableTTSAPI(
        model_path,
        vocos_path,
        "vocos"
    ).to(device)

    model.g2p_mapping["burmese"] = burmese_to_ipa2

    return model, ref_path


def translate_chinese_to_myanmar(text):

    if not text or not text.strip():
        return ""

    try:

        url = "https://translate.googleapis.com/translate_a/single"

        params = {
            "client": "gtx",
            "sl": "zh-CN",
            "tl": "my",
            "dt": "t",
            "q": text
        }

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        result = ""

        for item in data[0]:
            if item[0]:
                result += item[0]

        return result.strip()

    except Exception as e:

        st.warning(
            f"ဘာသာပြန်ရာမှာ Error ဖြစ်ပါတယ်: {e}"
        )

        return text


def create_myanmar_voice(
    tts,
    ref_path,
    text,
    output_path
):

    try:

        if not text.strip():
            return False

        audio, _ = tts.inference(
            text,
            ref_path,
            "burmese",
            step=12,
            solver="euler",
            cfg=3.0
        )

        audio = (
            audio
            .squeeze(0)
            .detach()
            .cpu()
            .numpy()
        )

        sf.write(
            str(output_path),
            audio,
            44100
        )

        return True

    except Exception as e:

        st.error(
            f"🇲🇲 Myanmar TTS Error: {e}"
        )

        return False


def get_audio_duration(audio_file):

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_file)
        ],
        capture_output=True,
        text=True
    )

    return float(result.stdout.strip())


def fit_audio_to_duration(
    input_audio,
    output_audio,
    target_duration
):

    try:

        current_duration = get_audio_duration(
            input_audio
        )

        if current_duration <= 0:
            return False

        speed = current_duration / target_duration

        # atempo supports 0.5 - 2.0
        speed = max(0.5, min(2.0, speed))

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_audio),
                "-filter:a",
                f"atempo={speed}",
                "-t",
                str(target_duration),
                str(output_audio)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        return True

    except Exception:

        return False


def create_silent_audio(
    output_audio,
    duration
):

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            str(duration),
            str(output_audio)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def create_final_video(
    video_file,
    dubbed_audio,
    output_file
):

    """
    Original Chinese audio ကို မယူဘဲ
    Myanmar dubbed audio တစ်ခုတည်းထည့်မယ်။
    """

    command = [
        "ffmpeg",
        "-y",

        "-i",
        str(video_file),

        "-i",
        str(dubbed_audio),

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

        str(output_file)
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:

        st.error(
            "Final Video ပြုလုပ်ရာမှာ Error ဖြစ်ပါတယ်\n\n"
            + result.stderr[-3000:]
        )

        return False

    return True


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header("⚙️ Settings")

whisper_model_name = st.sidebar.selectbox(
    "Whisper Model",
    [
        "base",
        "small"
    ],
    index=0
)

st.sidebar.info(
    "🇨🇳 Chinese audio ကိုဖတ်ပြီး "
    "🇲🇲 မြန်မာလို ဘာသာပြန်ကာ "
    "Myanmar TTS နဲ့ အသံပြန်ထည့်ပေးပါတယ်။"
)


# =========================================================
# VIDEO UPLOAD
# =========================================================

uploaded_video = st.file_uploader(
    "🎥 Chinese Drama Video တင်ပါ",
    type=["mp4", "mov", "mkv"]
)


# =========================================================
# MAIN
# =========================================================

if uploaded_video:

    st.video(uploaded_video)

    start_button = st.button(
        "🚀 Myanmar Dubbing စလုပ်မယ်",
        type="primary",
        use_container_width=True
    )

    if start_button:

        # -------------------------------------------------
        # TEMP DIRECTORY
        # -------------------------------------------------

        work_dir = Path(
            tempfile.mkdtemp(
                prefix="myanmar_dubbing_"
            )
        )

        input_video = (
            work_dir /
            uploaded_video.name
        )

        with open(
            input_video,
            "wb"
        ) as f:

            f.write(
                uploaded_video.getbuffer()
            )

        st.success(
            "Video upload ပြီးပါပြီ။"
        )

        # -------------------------------------------------
        # WHISPER
        # -------------------------------------------------

        progress = st.progress(0)

        status = st.empty()

        status.info(
            "🎙️ Whisper ကို load လုပ်နေပါတယ်..."
        )

        try:

            model = load_whisper()

        except Exception as e:

            st.error(
                f"Whisper Load Error: {e}"
            )

            st.stop()

        progress.progress(10)

        # -------------------------------------------------
        # TRANSCRIPTION
        # -------------------------------------------------

        status.info(
            "🇨🇳 Chinese စကားပြောတွေကို "
            "timestamp နဲ့ ဖတ်နေပါတယ်..."
        )

        try:

            result = model.transcribe(
                str(input_video),
                language="zh",
                task="transcribe",
                fp16=torch.cuda.is_available()
            )

        except Exception as e:

            st.error(
                f"Whisper Error: {e}"
            )

            st.stop()

        segments = result.get(
            "segments",
            []
        )

        if not segments:

            st.error(
                "Chinese dialogue မတွေ့ပါ။"
            )

            st.stop()

        progress.progress(25)

        st.success(
            f"📝 Dialogue {len(segments)} ခု တွေ့ပါတယ်။"
        )

        # -------------------------------------------------
        # MYSQL TTS LOAD
        # -------------------------------------------------

        status.info(
            "🇲🇲 Myanmar TTS model ကို load လုပ်နေပါတယ်..."
        )

        try:

            myanmar_tts, myanmar_ref = (
                load_myanmar_tts()
            )

        except Exception as e:

            st.error(
                "Myanmar TTS model load မဖြစ်ပါ။\n\n"
                f"{e}"
            )

            st.stop()

        progress.progress(35)

        # -------------------------------------------------
        # GET VIDEO DURATION
        # -------------------------------------------------

        video_duration = get_audio_duration(
            input_video
        )

        # -------------------------------------------------
        # CREATE FULL DUBBED AUDIO
        # -------------------------------------------------

        full_audio = (
            work_dir /
            "full_myanmar_audio.wav"
        )

        segment_audio_files = []

        status.info(
            "🇨🇳 Chinese → 🇲🇲 Myanmar ဘာသာပြန်ပြီး "
            "အသံထုတ်နေပါတယ်..."
        )

        # Start with silence
        create_silent_audio(
            full_audio,
            video_duration
        )

        # -------------------------------------------------
        # PROCESS EACH SEGMENT
        # -------------------------------------------------

        for index, segment in enumerate(
            segments
        ):

            start_time = float(
                segment["start"]
            )

            end_time = float(
                segment["end"]
            )

            duration = (
                end_time -
                start_time
            )

            chinese_text = (
                segment["text"]
                .strip()
            )

            if not chinese_text:
                continue

            # ---------------------------------------------
            # TRANSLATE
            # ---------------------------------------------

            myanmar_text = (
                translate_chinese_to_myanmar(
                    chinese_text
                )
            )

            # ---------------------------------------------
            # SHOW CURRENT
            # ---------------------------------------------

            st.write(
                f"**Scene {index + 1}**"
            )

            st.write(
                f"🇨🇳 {chinese_text}"
            )

            st.write(
                f"🇲🇲 {myanmar_text}"
            )

            # ---------------------------------------------
            # CREATE TTS
            # ---------------------------------------------

            raw_audio = (
                work_dir /
                f"tts_{index}.wav"
            )

            fitted_audio = (
                work_dir /
                f"tts_fit_{index}.wav"
            )

            created = create_myanmar_voice(
                myanmar_tts,
                myanmar_ref,
                myanmar_text,
                raw_audio
            )

            if not created:
                continue

            # ---------------------------------------------
            # FIT TTS TO ORIGINAL TIMING
            # ---------------------------------------------

            fitted = fit_audio_to_duration(
                raw_audio,
                fitted_audio,
                duration
            )

            if not fitted:
                continue

            segment_audio_files.append(
                (
                    start_time,
                    fitted_audio
                )
            )

            # ---------------------------------------------
            # PUT AUDIO INTO TIMELINE
            # ---------------------------------------------

            temp_full = (
                work_dir /
                f"timeline_{index}.wav"
            )

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",

                    "-i",
                    str(full_audio),

                    "-i",
                    str(fitted_audio),

                    "-filter_complex",

                    (
                        f"[1:a]"
                        f"adelay="
                        f"{int(start_time * 1000)}|"
                        f"{int(start_time * 1000)}"
                        f"[delayed];"
                        f"[0:a][delayed]"
                        f"amix=inputs=2:"
                        f"duration=first:"
                        f"dropout_transition=0"
                        f"[out]"
                    ),

                    "-map",
                    "[out]",

                    "-ar",
                    "44100",

                    "-ac",
                    "1",

                    str(temp_full)
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            if temp_full.exists():

                full_audio = temp_full

            # ---------------------------------------------
            # PROGRESS
            # ---------------------------------------------

            percent = (
                35 +
                int(
                    ((index + 1) /
                     len(segments))
                    * 45
                )
            )

            progress.progress(
                min(percent, 80)
            )

        # -------------------------------------------------
        # FINAL AUDIO
        # -------------------------------------------------

        progress.progress(85)

        status.info(
            "🎬 Myanmar dubbed audio ကို "
            "video ထဲထည့်နေပါတယ်..."
        )

        final_video = (
            work_dir /
            "Myanmar_Dubbed_Final.mp4"
        )

        success = create_final_video(
            input_video,
            full_audio,
            final_video
        )

        if not success:
            st.stop()

        progress.progress(100)

        status.success(
            "🎉 Myanmar Dubbing ပြီးပါပြီ!"
        )

        # -------------------------------------------------
        # RESULT
        # -------------------------------------------------

        st.subheader(
            "🎬 Final Myanmar Dubbed Video"
        )

        st.video(
            str(final_video)
        )

        with open(
            final_video,
            "rb"
        ) as f:

            st.download_button(
                label="⬇️ Myanmar Dubbed Video Download",
                data=f,
                file_name="Myanmar_Dubbed_Final.mp4",
                mime="video/mp4",
                use_container_width=True
            )

        st.success(
            "✅ မူရင်း Chinese audio ကို မထည့်ထားပါဘူး။ "
            "Myanmar dubbing audio ကိုပဲ ထည့်ထားပါတယ်။"
        )