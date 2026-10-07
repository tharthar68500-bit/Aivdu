import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import whisper


# =========================================================
# PAGE
# =========================================================

st.set_page_config(
    page_title="Chinese → Myanmar AI Auto Dubbing",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Chinese → Myanmar AI Auto-Dubbing")
st.write(
    "တရုတ် Drama Video ထည့်ပါ → တရုတ်စကားကို AI ကဖတ်မည် → "
    "မြန်မာလို ဘာသာပြန်မည် → မြန်မာ AI အသံပြန်သွင်းမည်"
)


# =========================================================
# SETTINGS
# =========================================================

st.sidebar.header("⚙️ Settings")

api_key = st.sidebar.text_input(
    "ElevenLabs API Key",
    type="password",
)

voice_male = st.sidebar.text_input(
    "👨 Male Voice ID",
    value="2EiwWnXFnvU5JabPnv8n",
)

voice_female = st.sidebar.text_input(
    "👩 Female Voice ID",
    value="21m00Tcm4TlvDq8ikWAM",
)

model_name = st.sidebar.selectbox(
    "Whisper Model",
    ["base", "small"],
    index=0,
)

keep_original_audio = st.sidebar.checkbox(
    "မူရင်းတရုတ်အသံ အနည်းငယ်ထားမလား?",
    value=False,
)

if keep_original_audio:
    original_volume = st.sidebar.slider(
        "မူရင်းအသံ Volume",
        0.0,
        0.30,
        0.05,
        0.01,
    )
else:
    original_volume = 0.0


# =========================================================
# WHISPER
# =========================================================

@st.cache_resource
def load_whisper_model(model_name):
    return whisper.load_model(model_name)


# =========================================================
# FFPROBE
# =========================================================

def get_duration(path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


# =========================================================
# TRANSLATION
# =========================================================

def translate_to_myanmar(text):
    """
    Chinese/other language → Myanmar
    Google Translate public endpoint for testing.
    """

    if not text.strip():
        return ""

    try:
        url = "https://translate.googleapis.com/translate_a/single"

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

        result = ""

        if data and data[0]:
            for item in data[0]:
                if item and item[0]:
                    result += item[0]

        return result.strip() if result.strip() else text

    except Exception as e:
        st.warning(f"ဘာသာပြန်ရာတွင် Error ဖြစ်ပါသည်: {e}")
        return text


# =========================================================
# ELEVENLABS TTS
# =========================================================

def generate_voice(
    text,
    voice_id,
    api_key,
    output_file,
):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }

    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.40,
            "similarity_boost": 0.75,
            "style": 0.20,
            "use_speaker_boost": True,
        },
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=120,
        )

        if response.status_code != 200:
            st.error(
                f"ElevenLabs Error {response.status_code}: "
                f"{response.text[:500]}"
            )
            return False

        with open(output_file, "wb") as f:
            f.write(response.content)

        return True

    except Exception as e:
        st.error(f"TTS Error: {e}")
        return False


# =========================================================
# SPEED AUDIO TO FIT TIMESTAMP
# =========================================================

def fit_audio_to_duration(
    input_audio,
    output_audio,
    target_duration,
):
    """
    TTS အသံကို မူရင်း dialogue duration နဲ့ နီးစပ်အောင်
    speed ပြောင်းပေးသည်။
    """

    if target_duration <= 0:
        return False

    # atempo supports 0.5 - 2.0 per filter.
    # Multiple filters allow wider range.
    current_duration = get_duration(input_audio)

    if current_duration <= 0:
        return False

    ratio = current_duration / target_duration

    filters = []

    # If TTS is longer than target,
    # speed it up.
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0

    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5

    if abs(ratio - 1.0) > 0.01:
        filters.append(f"atempo={ratio:.4f}")

    # Don't stretch too aggressively.
    if not filters:
        filters = ["anull"]

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_audio),
        "-filter:a", ",".join(filters),
        "-t", str(target_duration),
        "-ac", "2",
        "-ar", "44100",
        str(output_audio),
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


# =========================================================
# CREATE SILENCE AUDIO
# =========================================================

def create_silence(output_file, duration):
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_file),
    ]

    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


# =========================================================
# PUT AUDIO AT TIMESTAMP
# =========================================================

def create_dubbing_track(
    video_duration,
    audio_segments,
    output_file,
):
    """
    audio_segments:
        [
            {
                "file": "...mp3",
                "start": 1.2,
                "end": 4.5
            }
        ]
    """

    if not audio_segments:
        return False

    work_files = []

    try:
        # Full silence track
        silence_file = output_file.parent / "base_silence.wav"

        create_silence(
            silence_file,
            video_duration,
        )

        work_files.append(silence_file)

        inputs = [
            "-i",
            str(silence_file),
        ]

        filter_parts = [
            "[0:a]anull[base]"
        ]

        for i, item in enumerate(audio_segments):

            audio_file = item["file"]
            start = item["start"]

            inputs.extend([
                "-i",
                str(audio_file),
            ])

            delay_ms = max(0, int(start * 1000))

            filter_parts.append(
                f"[{i + 1}:a]"
                f"adelay={delay_ms}|{delay_ms},"
                f"apad"
                f"[a{i}]"
            )

        mix_inputs = "[base]"

        for i in range(len(audio_segments)):
            mix_inputs += f"[a{i}]"

        filter_parts.append(
            f"{mix_inputs}"
            f"amix=inputs={len(audio_segments) + 1}:"
            f"duration=first:"
            f"dropout_transition=0,"
            f"loudnorm=I=-16:TP=-1.5:LRA=11"
            f"[out]"
        )

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            str(video_duration),
            str(output_file),
        ]

        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )

        return True

    except Exception as e:
        st.error(f"Audio track ပြုလုပ်၍ မရပါ: {e}")
        return False

    finally:
        for f in work_files:
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass


# =========================================================
# FINAL VIDEO
# =========================================================

def create_final_video(
    original_video,
    dubbing_audio,
    output_video,
    keep_original,
    original_volume,
):
    """
    IMPORTANT:
    keep_original=False ဖြစ်ရင်
    မူရင်း Chinese dialogue မပါဘဲ Myanmar dubbing ပဲထွက်မယ်။
    """

    if keep_original:

        filter_complex = (
            f"[0:a]volume={original_volume}[orig];"
            f"[1:a]volume=1.0[dub];"
            f"[orig][dub]"
            f"amix=inputs=2:duration=first:"
            f"dropout_transition=0[a]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(original_video),
            "-i", str(dubbing_audio),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_video),
        ]

    else:

        # Original Chinese audio is COMPLETELY removed.
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(original_video),
            "-i", str(dubbing_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_video),
        ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        return True

    except subprocess.CalledProcessError as e:
        st.error(
            "Final video ပြုလုပ်၍ မရပါ။\n"
            + e.stderr.decode(errors="ignore")[-2000:]
        )
        return False


# =========================================================
# SPEAKER SELECTION
# =========================================================

def choose_voice(segment_index):
    """
    ယခု version မှာ speaker diarization မထည့်သေးပါ။
    Test အတွက် Male/Female ကို အလှည့်ကျသုံးသည်။

    နောက် version မှာ:
    Speaker A → Male
    Speaker B → Female
    Speaker C → Male
    စသဖြင့် AI speaker detection ထည့်နိုင်သည်။
    """

    if segment_index % 2 == 0:
        return voice_male, "Male"
    else:
        return voice_female, "Female"


# =========================================================
# CLEAN TEMP FILES
# =========================================================

def cleanup_folder(folder):
    try:
        shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass


# =========================================================
# UPLOAD
# =========================================================

st.subheader("📹 Chinese Drama Video တင်ပါ")

video = st.file_uploader(
    "Video File",
    type=["mp4", "mov", "mkv"],
)


# =========================================================
# PROCESS
# =========================================================

if st.button(
    "🚀 Chinese → Myanmar Dubbing စတင်မည်",
    type="primary",
):

    if not video:
        st.warning("⚠️ Video တင်ပေးပါ။")
        st.stop()

    if not api_key:
        st.warning("⚠️ ElevenLabs API Key ထည့်ပေးပါ။")
        st.stop()

    work_dir = Path(
        tempfile.mkdtemp(
            prefix="myanmar_dubbing_"
        )
    )

    try:

        # -------------------------------------------------
        # SAVE ORIGINAL VIDEO
        # -------------------------------------------------

        input_video = work_dir / "input.mp4"

        with open(input_video, "wb") as f:
            f.write(video.getbuffer())

        duration = get_duration(input_video)

        if duration <= 0:
            st.error("❌ Video duration ဖတ်၍မရပါ။")
            st.stop()

        if duration > 600:
            st.error(
                f"❌ Video သည် 10 မိနစ်ကျော်နေပါသည်။ "
                f"({duration / 60:.2f} minutes)"
            )
            st.stop()

        st.success(
            f"Video ကြာချိန်: {duration:.2f} seconds"
        )

        # -------------------------------------------------
        # LOAD WHISPER
        # -------------------------------------------------

        with st.spinner("🧠 Whisper AI ကိုဖွင့်နေပါသည်..."):
            model = load_whisper_model(model_name)

        # -------------------------------------------------
        # TRANSCRIBE
        # -------------------------------------------------

        with st.spinner(
            "🎧 တရုတ်စကားပြောကို စစ်ဆေးနေပါသည်..."
        ):

            result = model.transcribe(
                str(input_video),
                language="zh",
                task="transcribe",
                fp16=False,
                verbose=False,
            )

        segments = result.get("segments", [])

        if not segments:
            st.error(
                "❌ စကားပြော segment မတွေ့ပါ။"
            )
            st.stop()

        st.success(
            f"📝 Dialogue {len(segments)} ခု တွေ့ပါသည်။"
        )

        # -------------------------------------------------
        # PROCESS EACH SEGMENT
        # -------------------------------------------------

        audio_segments = []

        progress = st.progress(0)

        for index, segment in enumerate(segments):

            original_text = segment.get(
                "text",
                ""
            ).strip()

            start = float(
                segment.get("start", 0)
            )

            end = float(
                segment.get("end", start)
            )

            target_duration = end - start

            if not original_text:
                continue

            if target_duration <= 0:
                continue

            st.write(
                f"**#{index + 1}** "
                f"{start:.2f}s → {end:.2f}s"
            )

            st.caption(
                f"🇨🇳 {original_text}"
            )

            # -------------------------------------------------
            # TRANSLATE
            # -------------------------------------------------

            with st.spinner(
                f"🇲🇲 စာကြောင်း #{index + 1} ဘာသာပြန်နေပါသည်..."
            ):

                myanmar_text = translate_to_myanmar(
                    original_text
                )

            st.caption(
                f"🇲🇲 {myanmar_text}"
            )

            if not myanmar_text:
                continue

            # -------------------------------------------------
            # VOICE
            # -------------------------------------------------

            voice_id, gender = choose_voice(index)

            raw_voice = (
                work_dir
                / f"voice_raw_{index}.mp3"
            )

            fitted_voice = (
                work_dir
                / f"voice_fit_{index}.mp3"
            )

            with st.spinner(
                f"🎙️ {gender} မြန်မာအသံ ထုတ်နေပါသည်..."
            ):

                success = generate_voice(
                    myanmar_text,
                    voice_id,
                    api_key,
                    raw_voice,
                )

            if not success:
                continue

            # -------------------------------------------------
            # FIT VOICE TO ORIGINAL TIMING
            # -------------------------------------------------

            fitted = fit_audio_to_duration(
                raw_voice,
                fitted_voice,
                target_duration,
            )

            if not fitted:
                continue

            audio_segments.append(
                {
                    "file": fitted_voice,
                    "start": start,
                    "end": end,
                }
            )

            progress.progress(
                min(
                    1.0,
                    (index + 1) / len(segments)
                )
            )

        # -------------------------------------------------
        # CHECK AUDIO
        # -------------------------------------------------

        if not audio_segments:
            st.error(
                "❌ မြန်မာအသံတစ်ခုမှ မထုတ်နိုင်ပါ။"
            )
            st.stop()

        # -------------------------------------------------
        # BUILD FULL DUBBING TRACK
        # -------------------------------------------------

        st.info(
            "🎚️ မြန်မာအသံတွေကို မူရင်း timestamp "
            "အတိုင်း ပြန်တည်နေပါသည်..."
        )

        dubbing_audio = (
            work_dir
            / "myanmar_dubbing.m4a"
        )

        success = create_dubbing_track(
            duration,
            audio_segments,
            dubbing_audio,
        )

        if not success:
            st.error(
                "❌ Dubbing audio ပြုလုပ်၍မရပါ။"
            )
            st.stop()

        # -------------------------------------------------
        # FINAL VIDEO
        # -------------------------------------------------

        st.info(
            "🎬 Final Myanmar Dubbed Video ပြုလုပ်နေပါသည်..."
        )

        output_video = (
            work_dir
            / "Myanmar_Dubbed_Final.mp4"
        )

        success = create_final_video(
            input_video,
            dubbing_audio,
            output_video,
            keep_original_audio,
            original_volume,
        )

        if not success:
            st.error(
                "❌ Final video မထုတ်နိုင်ပါ။"
            )
            st.stop()

        # -------------------------------------------------
        # RESULT
        # -------------------------------------------------

        st.success(
            "✅ Myanmar Auto-Dubbing အောင်မြင်ပါပြီ!"
        )

        st.video(
            str(output_video)
        )

        with open(
            output_video,
            "rb"
        ) as f:

            st.download_button(
                label="📥 မြန်မာ Dubbed Video Download",
                data=f,
                file_name="Myanmar_Dubbed_Final.mp4",
                mime="video/mp4",
            )

    except Exception as e:

        st.error(
            f"❌ Processing Error: {e}"
        )

    finally:

        # Don't immediately delete work_dir here
        # because Streamlit still needs the output file
        pass