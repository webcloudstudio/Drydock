set -x
# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf targets 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
drydock status
read
drydock init Drydock
read
drydock status
read
drydock import Drydock docs/Drydock_Specification.md
read
drydock status
read
drydock analyze Drydock
read
drydock status
read
