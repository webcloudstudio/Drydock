DIR=/mnt/c/Users/barlo/projects/drydock
LIST="CommonMark CsvStat DrydockStats DupFind FxRates LayersTesting Quakes ReadingList Toml jq"
for kit in $LIST
do
    echo $kit
    [ ! -e "$kit/.git" ] || continue
    cd $DIR/uat/$kit
    echo "== $kit"
    rm -f /mnt/c/Users/barlo/projects/drydock/uat/$kit/.git/index.lock
    drydock uat report $kit
    git add --all
    git commit -m "updated"
    git push 2>/dev/null
    cd $DIR
done
