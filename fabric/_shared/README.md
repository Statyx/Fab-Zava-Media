# `fabric/_shared/` — plumbing every workload depends on

Nothing here talks to a specific Fabric artifact. If a module in this folder starts
knowing about ontologies or reports, it belongs in that workload's package instead.

| Module | Owns |
|---|---|
| `paths.py` | every filesystem location in the repository, resolved once from the root |
| `platform_env.py` | `PATH` repair from the Windows registry + UTF-8 stdout; the `bootstrap()` every script calls first |
| `helpers.py` | auth, async operation polling, item lookup, Kusto, OneLake tokens, config/state I/O |

## `paths.py` exists to kill a specific bug class

Deploy code is grouped by workload, so scripts sit at different depths.
`Path(__file__).parent.parent / "data"` is silently wrong the moment a file moves
between folders, and wrong in a way that surfaces minutes into a deploy. Import the
constant instead:

```python
from fabric._shared.paths import ARTIFACTS, CONTRACTS, CONFIG_FILE, STATE_FILE
```

## `platform_env.py` is duplicated verbatim across sibling repositories

Change it here and copy it over — do not edit one side only. `import winreg` must
appear nowhere else in the repository; a test asserts that, and CI runs it on Linux,
which is what turns the guarantee into more than a comment.
