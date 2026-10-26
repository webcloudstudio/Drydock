DIR=/mnt/c/Users/barlo/projects/drydock
for kit in "$DIR"/uat/*/; do
    [ -e "$kit/.git" ] || continue
    echo "== $kit"
    git -C "$kit" add --all
    git -C "$kit" commit -m "updated"
    git -C "$kit" push
done
