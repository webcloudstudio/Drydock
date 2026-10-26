DIR=/mnt/c/Users/barlo/projects/drydock
LIST="CommonMark CsvStat DrydockStats DupFind FxRates LayersTesting Quakes README.md ReadingList Toml jq"
set -x
for kit in $LIST
do
    echo $kit
    [ ! -e "$kit/.git" ] || continue
    cd $DIR/uat/$kit
    echo "== $kit"
    git add --all
    git commit -m "updated"
    cd $DIR
done
