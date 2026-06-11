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

Currently, questions, bugs and suggestions should be reported through [GitHub issue tracker](https://github.com/mackilanu/grimaur/issues).

## Coding convention

All rules/exclusions can be consulted in the master `pyproject.toml` file.

Use `ruff` and `shfmt` or `pre-commit` [file](/.pre-commit-config.yaml).

Why a single file?

`grimaur` is used in installer flows which make it one `curl` or `wget` away:

[rawlink](https://raw.githubusercontent.com/mackilanu/grimaur/master/grimaur)

---
