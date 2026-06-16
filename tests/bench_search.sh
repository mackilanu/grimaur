#!/bin/sh
# Cold-vs-warm search benchmark using plain `time`. Both queries score the bulk AUR
# metadata dump (aurmeta.json: name+version+description in one fetch, no per-package
# requests); cold pays the dump download+parse, warm is the cached scan. The patterns
# differ only in result-set size:
#   python  -> broad match
#   firefox -> narrow match
set -eu
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/grimoire/.searchcache"
grimoire="$(cd "$(dirname "$0")/.." && pwd)/grimoire"

# Scope to --repo AUR so this measures the dump path, not whatever else is in the
# user's repos.ini (a bare `search` aggregates every section, cloning custom aliases).
for pattern in python firefox; do
	echo "== $pattern: cold (cache cleared) =="
	rm -rf "$cache_dir"
	time python "$grimoire" search "$pattern" --repo AUR --no-interactive >/dev/null

	echo "== $pattern: warm =="
	time python "$grimoire" search "$pattern" --repo AUR --no-interactive >/dev/null
done

# list --repo AUR shares the same aurmeta.json dump as search, so cold-vs-warm here
# measures the dump fetch+cache too (now with versions, not just names).
echo "== list --repo AUR: cold (cache cleared) =="
rm -rf "$cache_dir"
time python "$grimoire" list --repo AUR >/dev/null

echo "== list --repo AUR: warm =="
time python "$grimoire" list --repo AUR >/dev/null
