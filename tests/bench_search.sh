#!/bin/sh
# Cold-vs-warm search benchmark using plain `time`. Both queries hit the git path
# (packages.json name list + srcinfo/<pkg>.json metadata cache); the patterns differ
# only in result-set size:
#   python  -> broad match, lots of metadata fetches on a cold cache
#   firefox -> narrow match, few metadata fetches
set -eu
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/grimoire/.searchcache"
grimoire="$(cd "$(dirname "$0")/.." && pwd)/grimoire"

for pattern in python firefox; do
	echo "== $pattern: cold (cache cleared) =="
	rm -rf "$cache_dir"
	time python "$grimoire" search "$pattern" --no-interactive >/dev/null

	echo "== $pattern: warm =="
	time python "$grimoire" search "$pattern" --no-interactive >/dev/null
done

# list --aur isolates the packages.json path: no per-package metadata involved,
# so cold-vs-warm here measures the name-list fetch+cache alone.
echo "== list --aur: cold (cache cleared) =="
rm -rf "$cache_dir"
time python "$grimoire" list --aur >/dev/null

echo "== list --aur: warm =="
time python "$grimoire" list --aur >/dev/null
