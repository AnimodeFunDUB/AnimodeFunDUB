# Changelog

## 2.1.0 — Studio edition (clean release)

**License and credit**
- Released under the MIT License, (c) 2026 Animode Fun DUB (see LICENSE and NOTICE).
- Added SPDX license/copyright headers to every Animode source file.
- Removed unused legacy training, evaluation and data-collection code, its configs, phase
  notes and the third-party license bundled with it. The Studio never imported that code.
- Removed legacy upstream documentation, including an unverified download link.

**Documentation**
- New terminal-style README with animated banner, language-flag matrix and credits.
- Added CONTRIBUTING.md.

**Studio**
- Added diagnostics, owned source copies and saved-project resuming.
- Added speaker/timestamp/script editing, revision checks and stale-edit protection.
- Added single-clip preview/regeneration and content-addressed synthesis caching.
- Added mastering, Hindi subtitle/CSV exports and character-track bundles.
- Added authenticated API, bounded subprocess queue and persistent task status.
- Added render locks, restart interruption status and source-overlap review.
- Updated Docker, Compose, Makefile, launchers and video batch processing.

The archive excludes release binaries, environments, generated media, secrets, bytecode and
caches. Heavy-model and GPU/Docker acceptance remain required.
