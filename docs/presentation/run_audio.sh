cd /mnt/c/Users/barlo/projects/drydock/docs/presentation
export SHVOICE=Andrew
export VOICE=en-US-AndrewNeural
#export VOICE=en-US-Andrew:DragonHDLatestNeural
set -x
uv run --python 3.12 --with edge-tts --with imageio-ffmpeg python make_talking_points_audio.py --keep-text --voice ${VOICE} --output audio/teleprompter_${SHVOICE}.mp3
