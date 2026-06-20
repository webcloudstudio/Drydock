set -x
PROJECT=Marina2
SOURCE=/mnt/c/Users/barlo/projects/Specifications/Marina

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
drydock status
read
drydock init $PROJECT
read
drydock status
read
drydock import $PROJECT $SOURCE --format markdown
read
drydock status
read
drydock analyze $PROJECT
read
drydock status
read
drydock plan create $PROJECT
read
