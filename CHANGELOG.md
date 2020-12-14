# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

### Update notes

Sharing of characters now requires the new permission `share_characters`. Please make sure to add the new permission accordingly to keep the sharing feature enabled.

### Added

### Changed

- Only users with the new permission `share_characters` can share their characters. ([#69](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/69))

### Fixed

- Non existing user are marked as compliant ([#59](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/59))

## [1.0.0b1] - 2020-12-07

### Change

- Updated README for beta release

### Fixed

- Fixed tox issue related to new PIP dependency resolver

## [1.0.0a15] - 2020-12-06

### Change

- Re-designed doctrines to the much broader concept of skill sets ([#58](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/58))

## [1.0.0a14] - 2020-12-04

### Change

- Former mailing lists  ([#57](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/57))
- More options for management commands

### Fix

- Asset update fails to report success when there was no change

## [1.0.0a13] - 2020-12-03

### Fix

- Stale identification not fully aligned with periodic update tasks

## [1.0.0a12] - 2020-12-03

### Added

- Ability to get measured durations of update process for system tuning

### Fixed

- Sorting order of characters on admin site

## [1.0.0a11] - 2020-12-02

### Changed

- Access to other characters require new permission (except for shared characters) ([#49](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/49))

## [1.0.0a10] - 2020-12-01

### Changed

- Further improvement of the asset update process ([#56](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/56))

## [1.0.0a9] - 2020-11-30

### Changed

- Reduce update load by enabling skipping of updates when data has not changed

## [1.0.0a8] - 2020-11-28

### Fixed

- Assets update process is visible to the user ([#56](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/56))

## [1.0.0a7] - 2020-11-25

### Changed

- don't show permissions we don't use ([!4](https://gitlab.com/ErikKalkoken/aa-memberaudit/-/merge_requests/4))

### Fixed

- Handle ESI error from resolving mailing lists as sender in mails ([#54](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/55))

## [1.0.0a6] - 2020-11-20

### Changed

- Changed approach: Structure resolving exceeds ESI error rate limit ([#53](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/53))

## [1.0.0a5] - 2020-11-19

### Fixed

- Fix to be confirmed: Structure resolving exceeds ESI error rate limit ([#53](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/53))

## [1.0.0a4] - 2020-11-18

### Fixed

- Unknown mailing list IDs are crashing mail update and halting EveEntity ID resolution for all apps ([#51](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/51))
- Wrong character count in compliance report ([#52](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/52))

## [1.0.0a3] - 2020-11-17

### Fixed

- Can't see alts of other alliance mains ([#45](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/45))
- Change report restriction ([#49](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/49))

## [1.0.0a2] - 2020-11-14

### Added

- Add durations to corp history ([#43](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/42))

### Fixed

- Attempt: Fix not-yet-loaded mail behavior ([#40](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/42))
- Disable vertical slider for tables in character finder, reports ([#40](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/41))

## [1.0.0a1] - 2020-11-12

### Added

- Initial alpha release
