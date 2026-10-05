# Maintenance

Dependency and GitHub Actions updates are proposed weekly by Dependabot (the native `uv` ecosystem maintains `uv.lock`), with grouped updates and a small open-PR limit. Review behavior changes and merge only after required CI passes; automatic merging and mandatory human approvals are not configured.

External Actions are pinned to verified full commit SHAs with readable version comments. Update the SHA and comment together. Pinning an Action implementation does not freeze a Rust stable toolchain or every transitive package; committed lockfiles define the resolved dependencies where available.

Main should reject force pushes and deletion and require a pull request with the always-running CI checks listed below. No human approval is required. Required checks must not use workflow-level PR path filters, which can leave documentation or dependency PRs pending indefinitely. Keep check names stable or migrate the ruleset when changing them.

Release tags must match package and Action binary versions where applicable. Validate tests, build artifacts, metadata and clean installs before publishing. Python packages use PyPI Trusted Publishing; binary Actions verify the selected release archive against its SHA256SUMS before running it. Never replace assets on an already published release. Versioned integration dependencies are updated explicitly and compatibility is checked before adoption.

Required CI: `lint`, `tests (3.11)`, `tests (3.12)`, `tests (3.14)` and `build`. CI uses the committed uv lockfile. Publishing consumes one wheel and one sdist already attached to the explicitly selected GitHub Release; validate their embedded package identity/version and the selected source tag before PyPI publication.
