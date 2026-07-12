 List available voices:

  uv run --python 3.12 --with edge-tts edge-tts --list-voices

  Filter likely English voices:

  uv run --python 3.12 --with edge-tts edge-tts --list-voices | rg "en-US|
  en-GB|en-AU|en-CA"

  Common good options:

  en-US-AvaMultilingualNeural      # current voice, same as release video
  en-US-AvaNeural
  en-US-EmmaNeural
  en-US-JennyNeural
  en-US-AriaNeural
  en-US-MichelleNeural
  en-US-GuyNeural
  en-US-DavisNeural
  en-US-AndrewNeural
  en-GB-SoniaNeural
  en-GB-RyanNeural
  en-AU-NatashaNeural
  en-AU-WilliamNeural

  Set the voice when generating:

  uv run --python 3.12 --with edge-tts --with imageio-ffmpeg \
    python docs/presentation/make_talking_points_audio.py \
    --voice en-US-JennyNeural \
    --output docs/presentation/audio/teleprompter_jenny.mp3 \
    --keep-text

  You can also tune speed and volume:

  uv run --python 3.12 --with edge-tts --with imageio-ffmpeg \
    python docs/presentation/make_talking_points_audio.py \
    --voice en-US-GuyNeural \
    --rate "-5%" \
    --volume "+0%" \
    --output docs/presentation/audio/teleprompter_guy.mp3

  Useful script options now are:

  --voice      Edge TTS voice name
  --rate       speaking speed, for example "-10%", "+5%", "+0%"
  --volume     volume adjustment, for example "+0%", "+10%", "-10%"
  --line-gap   breath between spoken lines, default 0.35 seconds
  --pause      duration for "( pause )", default 1.0 seconds
  --print-text preview exact spoken text without generating audio
  --keep-text  write the exact spoken text next to the MP3

  Example for a slower review listen:

  uv run --python 3.12 --with edge-tts --with imageio-ffmpeg \
    python docs/presentation/make_talking_points_audio.py \
    --voice en-US-AndrewNeural \
    --rate "-8%" \
    --line-gap 0.45 \
    --pause 1.25 \
    --output docs/presentation/audio/teleprompter_andrew_slow.mp3 \
    --keep-text
