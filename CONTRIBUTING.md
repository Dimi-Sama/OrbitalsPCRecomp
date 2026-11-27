# Contributing to Orbitals PC Recomp

Open feature and fix pull requests against **`dev`**. Start from the current `dev` branch and resolve any conflicts on your PR branch before integration.

## Pull requests

- Keep each PR focused on one change that reviewers can test independently.
- Explain what changes and whether an existing `Orbitals_code.dll` or `Orbitals_code.so` can be reused. Runtime-only updates can reuse a compatible module. Changes to code generation or the runtime–module interface need a rebuild when the build fingerprint changes.
- List the platforms, commands and in-game scenarios you actually tested. For graphics or performance changes, compare the same scene and settings before and after. For a build or update change, record the path the launcher took and whether the game started.

See the [build guide](BUILDING.md) and [launcher update guide](launcher/README.md#updating-an-installation). Keep game dumps, saves, shader caches and recompiled game modules out of pull requests.

## Release branches

- **`dev`** is the integration branch. Review and test each PR before merging it.
- **`release/vX.Y.Z`** branches from `dev` when testing begins for that release. Continue new work on `dev`, fix release blockers there, then bring the individual fixes into the candidate for retesting.
- **`main`** holds stable releases. Once Dimitry approves the candidate, merge it into `main`, tag that stable commit as `vX.Y.Z`, and publish its release assets.
