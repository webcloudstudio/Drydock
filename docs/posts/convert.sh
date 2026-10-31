
for j in `echo claudecode claudeworkflows codex`
do
	echo $j
	drydock publish $j.md --output $j.html --theme slate
done
