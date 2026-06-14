#!/bin/sh
# Cold-vs-warm search benchmark using plain `time`, one query per backend:
#   python  -> AUR RPC refuses ("too many results"), exercises the git
#              mirror fallback: packages.json list + srcinfo/ metadata cache
#   firefox -> narrow enough for the AUR RPC (if it is not down), exercises
#              the cached search/<sha>.json response
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

# list --aur isolates the packages.json path: no srcinfo or RPC involved,
# so cold-vs-warm here measures the name-list fetch+cache alone.
echo "== list --aur: cold (cache cleared) =="
rm -rf "$cache_dir"
time python "$grimoire" list --aur >/dev/null

echo "== list --aur: warm =="
time python "$grimoire" list --aur >/dev/null
