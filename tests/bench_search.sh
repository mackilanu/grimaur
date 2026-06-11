#!/bin/sh
# Cold-vs-warm search benchmark using plain `time`, one query per backend:
#   python  -> AUR RPC refuses ("too many results"), exercises the git
#              mirror fallback: packages.json list + srcinfo/ metadata cache
#   firefox -> narrow enough for the AUR RPC (if it is not down), exercises
#              the cached search/<sha>.json response
set -eu
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/grimaur"
grimaur="$(cd "$(dirname "$0")/.." && pwd)/grimaur"

for pattern in python firefox; do
	echo "== $pattern: cold (cache cleared) =="
	rm -rf "$cache_dir"
	time python "$grimaur" search "$pattern" --no-interactive >/dev/null

	echo "== $pattern: warm =="
	time python "$grimaur" search "$pattern" --no-interactive >/dev/null
done
