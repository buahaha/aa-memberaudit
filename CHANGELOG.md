# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [Unreleased] - yyyy-mm-dd

## [1.4.0] - 2021-07-01

### Added

- Will now send daily reminder notifications to users if their character tokens become invalid.

## [1.3.3] - 2021-06-30

### Changed

- Will no longer run updates during the daily downtime

### Fixed

- Trying to update a character on admin site gives error 500

## [1.3.2] - 2021-05-18

### Fixed

- Trying to fetch deleted mail results in 404s repeatedly (#94)

## [1.3.1] - 2021-05-04

### Changed

- Permissions `view_same_corporation` and `view_same_alliance` will now give access to other characters from **all** corporations / alliances the user's characters belong to. Not only the main character.

### Fixed

- Trying to delete a character from the admin site results in timeouts.
- Make badges fit into the menu

## [1.3.0] - 2021-04-17

### Added

- Show attributes for characters

### Changed

- Disabled fetching EveAncestry objects since current ESI bug is causing HTTP errors. See also: https://github.com/esi/esi-issues/issues/1264
- Performance tuning for various view queries

Big thanks to @gray_73 for the feature contribution!

### Fixed

- Added missing tables to drop_tables SQL

## [1.2.1] - 2021-02-18

### Added

- Added user state information to user compliance and skill set reports

### Changed

- Removed guests from user compliance report
- Removed guests from corporations compliance reports
- Removed guests from skill set reports
- Character sidebar now also shows unregistered characters
- Clicking on unaccessible characters in the character sidebar on longer links to a "no permission" page; instead the link has been removed.

## [1.2.0] - 2021-02-16

### Added

- New details window for skill sets showing in detail which skills need to be trained
- New report for corporation compliance
- Additional filters for the character finder

### Changed

- Moved utils into it's own distribution package: allianceauth-app-utils

Thank you @gray_73 for your contribution to this release.

## [1.1.1] - 2021-01-29

### Added

- Additional filters and columns for character finder

### Changed

- Switched from local to on-demand swagger spec
- Improved protection of tasks against ESI outage and exceeded ESI error limits

## [1.1.0] - 2021-01-25

### Added

- Wallet transactions ([#88](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/88))
- Red/green coloring of wallet amounts like in the Eve client

## [1.0.2] - 2021-01-22

### Changed

- Refactor and split models ([#66](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/66))

### Fixed

- Incompatible with django-redis-cache 3.0 ([#90](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/90))

### Changed

## [1.0.1] - 2021-01-16

### Changed

- Performance improvements for update tasks ([#85](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/85))
- Improved resilience against ESI timeouts during transactions ([#87](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/87))
- Improved protection against 420 error when running an update ([#83](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/83))

### Fixed

- Layout error for user with no main in reports ([#86](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/86))

## [1.0.0] - 2021-01-05

### Fixed

- Shows correct icons for BPC and BPOs
- SkillSet reports: 'NoneType' object has no attribute 'portrait_url' ([#81](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/81))

## [1.0.0b3] - 2020-12-24

### Added

- Data retention limits for mail, contracts, wallet ([#75](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/75))
- Show and filter NPCs/agents in contact list ([#63](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/63))
- Autocomplete drop-down for skills and ship_type in skill sets
- Improved statistics with memberaudit_stats
- More filters and better sorting on admin site

### Changed

- Default values for MEMBERAUDIT_UPDATE_STALE_RING_x now rounded to full hours

### Fixed

- Require minimum version of django-eveuniverse for fix ([#71](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/71))
- Icon for SKINs not shown in assets and contracts ([#50](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/50))
- Workaround to prevent character details update aborts ([#77](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/77))

## [1.0.0b2] - 2020-12-14

### Update notes

The feature for sharing ones characters now requires the new permission `share_characters`. To keep the sharing feature enabled, please make sure to assign this new permission accordingly (e.g. to the guest state).

### Added

- `App_totals` added to **memberaudit_stats** command

### Changed

- Only users with the new permission `share_characters` can share their characters. ([#69](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/69))

### Fixed

- Non existing user are marked as compliant ([#59](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/59))
- Character encoding/escaping ([#60](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/60))
- Corp history not reading correctly ([#68](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/68))
- Workaround to deal with broken ESI ancestry endpoint. ([#70](https://gitlab.com/ErikKalkoken/aa-memberaudit/issues/70))

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
