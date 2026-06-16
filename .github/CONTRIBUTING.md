# Contribution guide !

## Fork and branch

```
# fork first
git checkout <existing>
git checkout -b <new>
git add <file(s)>
git commit
# describe what this commit fixes, ideally one fix per commit
git push
```

## Discussions

Bugs and concrete feature requests, should be reported through [GitHub issues tracker](https://github.com/mackilanu/grimoire/issues)

Questions, and suggestions in [GitHub discussions](https://github.com/mackilanu/grimoire/discussions)

## Coding convention

All rules/exclusions can be consulted in the master `pyproject.toml` file.

Tools used to code this mess: `pyright` `mypy` `ruff` `vulture`

## Why a single file?

`grimoire` is used in installer flows, which make it one `curl` or `wget` away:

[rawlink](https://raw.githubusercontent.com/mackilanu/grimoire/master/grimoire)

---
