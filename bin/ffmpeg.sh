cd /mnt/c/Users/barlo/projects/Drydock/docs
ffmpeg     -i ./presentation/Drydock_Video.mp4     -vf scale=min(1920,iw):-2     -c:v libx264     -preset slow     -crf 28     -pix_fmt yuv420p     -movflags +faststart     -c:a aac     -b:a 96k ./presentation/Drydock_Video.web.mp4
