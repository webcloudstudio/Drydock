# https://github.com/commonmark/commonmark-spec
# https://spec.commonmark.org/0.31.2/

rm -rf ../commonmark
rm -rf ./targets/commonmark

drydock config show
drydock init 	 commonmark

drydock import 	 commonmark --format markdown ../commonmark-spec/INSTRUCTIONS.md
drydock import 	 commonmark --format markdown ../commonmark-spec/spec.txt
drydock import 	 commonmark --format markdown ../commonmark-spec/test/spec_tests.py
drydock import 	 commonmark --format markdown ../commonmark-spec/test/cmark.py
drydock import 	 commonmark --format markdown ../commonmark-spec/test/normalize.py

drydock analyze  commonmark

drydock status 	 commonmark

drydock plan 	 commonmark

drydock validate commonmark

drydock build 	 commonmark
