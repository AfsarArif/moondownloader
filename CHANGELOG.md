# Changelog

All notable changes to Moon Downloader will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [14.1]

### Added
- Stall detection with automatic lane kills for genuinely slow downloads
- Per-URL retry with exponential backoff
- Live telemetry with `.log` and `.json` output
- CLI variant (`gen_cli.py`) for headless / multi-IP deployment
- Ad overlay bypass and popup dismissal on datanodes.to

### Changed
- Default browser worker count tuned to 16 for typical 40+ file sessions
- Improved dead-link detection so failures fail fast instead of timing out
- Resource blocking widened to cover more analytics/ad domains

### Fixed
- Resume interrupted downloads via `.tmp` files instead of restarting
- Range-header edge case when server returns 200 instead of 206

## [14.0]

### Added
- Initial public release
- datanodes.to and fuckingfast.co provider support
- Tkinter GUI with dual progress bars and color-coded log
