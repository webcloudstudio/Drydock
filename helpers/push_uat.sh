cd /mnt/c/Users/barlo/projects/drydock/uat

for d in */; do
	cd /mnt/c/Users/barlo/projects/drydock/uat/$d
	git add --all 
	git commit -qm "auto-push"
	echo "$d committed"
done
# for d in */; do (cd "$d" && git remote get-url origin &>/dev/null && git push -q && echo "$d pushed"); done
