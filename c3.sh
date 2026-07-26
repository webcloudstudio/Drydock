
# https://github.com/commonmark/commonmark-spec
# https://spec.commonmark.org/0.31.2/

rm -rf ../commonmark
rm -rf ./targets/commonmark

drydock config show
drydock init 	 commonmark

drydock import 	 commonmark --format markdown ../commonmark-spec//INSTRUCTIONS.md
drydock import 	 commonmark --format markdown ../commonmark-spec//spec.txt
drydock import 	 commonmark --format markdown ../commonmark-spec//test/spec_tests.py
drydock import 	 commonmark --format markdown ../commonmark-spec//test/cmark.py
drydock import 	 commonmark --format markdown ../commonmark-spec//test/normalize.py

drydock analyze  commonmark
drydock status 	 commonmark
drydock plan 	 commonmark
drydock validate commonmark
drydock build 	 commonmark

n=1; max=5
while drydock status "commonmark" --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"
  drydock build commonmark
  n=$((n+1)); [ "$n" -ge "$max" ] && { echo "hit $max build iterations — aborting"; exit 1; }
done
