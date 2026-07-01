source /mnt/c/Users/barlo/projects/Drydock/.venv/bin/activate

export UV_PUBLISH_TOKEN="$(awk '
    $0=="[pypi]" {in_pypi=1; next}
    /^\[/ && $0!="[pypi]" {in_pypi=0}
    in_pypi && $1=="password" {print $3; exit}
  ' ~/.pypirc)"
# echo $UV_PUBLISH_TOKEN

# uv build
cd /mnt/c/Users/barlo/projects/Drydock
rm -rf dist/
python3 -m hatchling build
unzip -l dist/drydock_sdd-*.whl
uv publish dist/*
