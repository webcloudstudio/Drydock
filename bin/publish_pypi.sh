# uv build
cd /mnt/c/Users/barlo/projects/Drydock
rm -rf dist/
python -m hatchling build
unzip -l dist/drydock_sdd-*.whl
uv publish dist/*
