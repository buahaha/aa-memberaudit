# Member Audit

An Alliance Auth app that provides full access to Eve characters and related reports for auditing, vetting and monitoring.

[![release](https://img.shields.io/pypi/v/aa-memberaudit?label=release)](https://pypi.org/project/aa-memberaudit/)
[![python](https://img.shields.io/pypi/pyversions/aa-memberaudit)](https://pypi.org/project/aa-memberaudit/)
[![django](https://img.shields.io/pypi/djversions/aa-memberaudit?label=django)](https://pypi.org/project/aa-memberaudit/)
[![pipeline](https://gitlab.com/ErikKalkoken/aa-memberaudit/badges/master/pipeline.svg)](https://gitlab.com/ErikKalkoken/aa-memberaudit/-/pipelines)
[![codecov](https://codecov.io/gl/ErikKalkoken/aa-memberaudit/branch/master/graph/badge.svg?token=QHMCUAFZBV)](https://codecov.io/gl/ErikKalkoken/aa-memberaudit)
[![license](https://img.shields.io/badge/license-MIT-green)](https://gitlab.com/ErikKalkoken/aa-memberaudit/-/blob/master/LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![chat](https://img.shields.io/discord/790364535294132234)](https://discord.gg/zmh52wnfvM)

## Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Highlights](#highlights)
- [Installation](#installation)
- [Updating](#updating)
- [Permissions](#permissions)
- [Settings](#settings)
- [Management Commands](#management-commands)
- [Authors](#authors)
- [Change Log](CHANGELOG.md)

## Overview

Member Audit is an Alliance Auth app that provides full access to Eve characters and related reports.

Users can monitor their characters, recruiters can vet the characters of applicants and leadership can audit the characters of their members to ensure compliance and find spies.

In addition character based reports gives leadership another valuable tool for managing their respective organization.

> **Help wanted**: We are looking for help with translating this app into multiple languages, i.e. Chinese, German and Spanish. If you are interested you can sign up [here](https://www.transifex.com/kalkoken-apps/aa-memberaudit/dashboard/).

## Key Features

Member Audit adds the following key features to Auth:

- Users can see an overview of all their characters with key information like their current location and wallet balance
- Users can get full access to their characters to monitor them without having to open the Eve client (similar to the classic Eve ap "EveMon").
- Applicants can temporarily share their characters with recruiters for vetting
- Leadership can get full access to characters of their members for auditing (e.g. to check suspicious members)
- Full access to characters currently includes the following information:
  - Assets
  - Bio
  - Contacts
  - Contracts
  - Corporation history
  - Implants
  - Jump clones
  - Mails
  - Loyalty points
  - Skill queue
  - Skill sets
  - Skills
  - Wallet (journal and transactions)

- Leadership can define Skill Sets, which are a way of defining skills needed to perform a specific activity or fly a doctrine ship. They allow recruiters and leadership to see at a glance what a character can do (e.g. which doctrine ships he/she can fly)
- Leadership can see reports and analytics about their members. Those currently include:
  - Compliance: if users have added all their characters
  - Skill Sets: which character has which skill sets

- Admins can use the flexible permission system to grant access levels for different roles (e.g. corp leadership may only have access to reports about their own corp members)
- Admins can customize and configure Member Audit to fit their needs. e.g. change the app's name and define how often which type of data is updated from the Eve server

- Designed to work efficiently with large number of characters
- Data retention policy allows managing storage capacity needs

## Highlights

### Character Launcher

The main page for users to register their characters and get a key infos of all registered characters.

![launcher](https://i.imgur.com/v9AU3Gr.jpg)

### Character Viewer

The page for displaying all details about a character.

![viewer](https://i.imgur.com/vo1N3kg.jpg)

### Skill Sets

Skill sets are a way of defining both required and recommended skills for a specific activity or ship.

This tab on the character view allows you to view what skill sets a character has. For skill sets they don't have or are missing parts of, it also shows what skills are missing.

![skill-plans](https://i.imgur.com/cKNy5vz.png)

Requirements can be customized per skill set in the administration panel. Recommended skill levels can be added in addition to requirements.

![skill-set-admin](https://i.imgur.com/ef2cCd9.png)

### Character Finder

On this page recruiters and leadership can look for other characters to view (assuming they have been given permission).

![finder](https://i.imgur.com/4sDnBcz.png)

## Installation

### Preconditions

1. Member Audit is a plugin for Alliance Auth. If you don't have Alliance Auth running already, please install it first before proceeding. (see the official [AA installation guide](https://allianceauth.readthedocs.io/en/latest/installation/auth/allianceauth/) for details)

2. Member Audit needs the app [django-eveuniverse](https://gitlab.com/ErikKalkoken/django-eveuniverse) to function. Please make sure it is installed, before before continuing.

### Step 1 - Install app

Make sure you are in the virtual environment (venv) of your Alliance Auth installation. Then install the newest release from PyPI:

```bash
pip install aa-memberaudit
```

### Step 2a - Configure Auth settings

Configure your Auth settings (`local.py`) as follows:

- Add `'memberaudit'` to `INSTALLED_APPS`
- Add below lines to your settings file:

```python
CELERYBEAT_SCHEDULE['memberaudit_run_regular_updates'] = {
    'task': 'memberaudit.tasks.run_regular_updates',
    'schedule': crontab(minute=0, hour='*/1'),
}
```

- Optional: Add additional settings if you want to change any defaults. See [Settings](#settings) for the full list.

### Step 2b - Configure celery settings

To remove clutter from your log file we recommend to change the default log message for successful tasks, so that results are no longer shown in the log.

For that make the following changes to your `celery.py`:

Add a new import at the top:

```python
from celery.app import trace
```

Add these lines the bottom of the file for the new log config:

```python
# Remove result from default log message on task success
trace.LOG_SUCCESS = "Task %(name)s[%(id)s] succeeded in %(runtime)ss"
```

> **Hint**<br>This change is recommended, but not strictly required to run Member Audit.

> **Note**<br>If accepted this change may also become part of the standard Auth configuration. See also this [merge request](https://gitlab.com/allianceauth/allianceauth/-/merge_requests/1273/diffs).

### Step 3 - Finalize App installation

Run migrations & copy static files

```bash
python manage.py migrate
python manage.py collectstatic
```

Restart your supervisor services for Auth

### Step 4 - Update EVE Online API Application

Update the Eve Online API app used for authentication in your AA installation to include the following scopes:

- `esi-assets.read_assets.v1`
- `esi-bookmarks.read_character_bookmarks.v1`
- `esi-calendar.read_calendar_events.v1`
- `esi-characters.read_agents_research.v1`
- `esi-characters.read_blueprints.v1`
- `esi-characters.read_contacts.v1`
- `esi-characters.read_fatigue.v1`
- `esi-characters.read_fw_stats.v1`
- `esi-characters.read_loyalty.v1`
- `esi-characters.read_medals.v1`
- `esi-characters.read_notifications.v1`
- `esi-characters.read_opportunities.v1`
- `esi-characters.read_standings.v1`
- `esi-characters.read_titles.v1`
- `esi-clones.read_clones.v1`
- `esi-clones.read_implants.v1`
- `esi-contracts.read_character_contracts.v1`
- `esi-corporations.read_corporation_membership.v1`
- `esi-industry.read_character_jobs.v1`
- `esi-industry.read_character_mining.v1`
- `esi-killmails.read_killmails.v1`
- `esi-location.read_location.v1`
- `esi-location.read_online.v1`
- `esi-location.read_ship_type.v1`
- `esi-mail.organize_mail.v1`
- `esi-mail.read_mail.v1`
- `esi-markets.read_character_orders.v1`
- `esi-markets.structure_markets.v1`
- `esi-planets.manage_planets.v1`
- `esi-planets.read_customs_offices.v1`
- `esi-search.search_structures.v1`
- `esi-skills.read_skillqueue.v1`
- `esi-skills.read_skills.v1`
- `esi-universe.read_structures.v1`
- `esi-wallet.read_character_wallet.v1`

### Step 5 - Verify Celery configuration

This app makes very heavy use of Celery and may run thousands of tasks every hour.

**Please make sure your celery configuration meets the following minimum requirements or Member Audit may overwhelm your server**:

- 10 workers (more is better)
- Tasks can be executed continuously without degrading overall server performance
- Task priorities are enabled

Please see [Celery Configuration](#celery-configuration) for details on how to configure celery accordingly.

> **Note**<br>When the above requirements are met Member Audit will also run smoothly on smaller servers.

### Step 6 - Load Eve Universe map data

In order to be able to select solar systems and ships types for trackers you need to load that data from ESI once. If you already have run those commands previously you can skip this step.

Load Eve Online map:

```bash
python manage.py eveuniverse_load_data map
```

```bash
python manage.py memberaudit_load_eve
```

You may want to wait until the loading is complete before continuing.

> **Hint**: These command will spawn a thousands of tasks. One easy way to monitor the progress is to watch the number of tasks shown on the Dashboard.

### Step 7 - Setup permissions

Finally you want to setup permission to define which users / groups will have access to which parts of the app. Check out [permissions](#permissions) for details.

Congratulations you are now ready to use Member Audit!

## Updating

To update your existing installation of Member Audit first enable your virtual environment.

Then run the following commands from your AA project directory (the one that contains `manage.py`).

```bash
pip install -U aa-memberaudit
```

```bash
python manage.py migrate
```

```bash
python manage.py collectstatic
```

Finally restart your AA supervisor services.

## Permissions

For this app there are two types of permissions:

- Feature permissions give access to a feature
- Scope permissions give access to scope

To define a role you will mostly need at least one permission from each type. For example for the recruiter role you will want `finder_access`, that gives access to the character finder tool, and `view_shared_characters`, so that the recruiter can see all shared characters.

The exception is the basic role, `basic_access`, that every user needs just to access the app. It does not require any additional scope roles, so a normal user just needs that role to be able to register his characters.

### Permission list

Name | Description | Type
-- | -- | --
`basic_access`| Can access this app and register and view own characters | Feature
`share_characters`| Can share his characters. Note that others need the `view_shared_characters` permission to see them.  | Feature
`finder_access`| Can access character finder features for accessing characters from others | Feature
`reports_access`| Can access reports features for seeing reports and analytics. | Feature
`characters_access`| Can access characters owned by others. | Feature
`view_shared_characters`| All characters, which have been marked as shared & can access these characters | Feature & Scope
`view_same_corporation`| All mains - incl. their alts -  of the same corporation | Scope
`view_same_alliance`| All mains - incl. their alts -  of the same alliance | Scope
`view_everything`| All characters registered with Member Audit | Scope

> **Hint**<br>All permissions can be found under the category "memberaudit | general".

### Example Roles

To further illustrate how the permission system works, see the following list showing which permissions are needed to define common roles:

Role | Description | Permissions
-- | -- | --
Normal user | Can use this app and register and access own characters | `basic_access`
Recruiter | Can access shared characters | `basic_access`<br>`finder_access`<br>`view_shared_characters`
Corporation Leadership | Can access reports for his corporation members (but can not access the characters) | `basic_access`<br>`reports_access`<br>`view_same_corporation`
Corp Leadership & Recruiter | Can access shared characters | `basic_access`<br>`finder_access`<br>`view_shared_characters`<br>`reports_access`<br>`view_same_corporation`
Alliance Auditor | Can search for and access all characters of his alliance  | `basic_access`<br>`finder_access`<br>`characters_access`<br>`view_same_alliance`

> **Note**<br>Naturally, superusers will have access to everything, without requiring permissions to be assigned.

## Celery configuration

### Task throughput

This app makes heavy use of Celery and will often run thousands of tasks per hour. Auth's default Celery setup is not well suited for handling high task volumes though (e.g. it will only spawn one worker per core, which scale badly due to high CPU usage). We strongly recommend to switch to a thread based setup (e.g. gevent), which has been proven to be significantly more efficient for running Auth.

For details on how to configure celery workers with threads please see [this section](https://allianceauth.readthedocs.io/en/latest/maintenance/tuning/celery.html#increasing-task-throughput) in the Auth's documentation.

When switching to thread based workers please also make sure to setup measure to protect against memory leak. The default celery options will not work for threads. See [this section](https://allianceauth.readthedocs.io/en/latest/maintenance/tuning/celery.html#supervisor) for details.

### ESI connection pool

If you have more than 10 workers you also need to increase the connection pool for django-esi accordingly. See [here](https://gitlab.com/allianceauth/django-esi/-/blob/master/esi/app_settings.py#L32) for the corresponding setting.

### Celery priorities

Last, but not least, please make sure your Celery is configured to run with priorities. This should be the default for all current Auth installation, but if you have an older installation you may have missed this change. Please see [these release notes](https://gitlab.com/allianceauth/allianceauth/-/releases/v2.6.3) for details.

### Member Audit configuration

The goal of an optimal configuration for Member Audit is that your system can complete all update tasks for your character within the respective update cycle.

For this you need to consider the following three factors:

- Number of characters to update
- Task throughput
- Update frequency

The number of characters depend on your organization. You an usually not influence this factor much and want to make sure that your system has sufficient room for that growth.

Your task throughout is defined by the number of celery workers. The more workers you have, the higher your potential throughput, so you may want to maximize that number for your system.

You can adjust the update frequency to meet your needs. For example if you have a lot of characters and your update tasks can not (or only barely) complete within the update cycle, then you can lengthen your update cycles to compensate. There are 3 update cycles called rings, which can be configured individually. See `MEMBERAUDIT_UPDATE_STALE_RING_x` in [settings](#settings) for details.

> **Hint**<br>You can use the management command **memberaudit_stats** to get current data about the last update runs, which can be very helpful to find the optimal configuration. See [memberaudit_stats](#memberaudit_stats) for details.

## Settings

Here is a list of available settings for this app. They can be configured by adding them to your AA settings file (`local.py`).

Note that all settings are optional and the app will use the documented default settings if they are not used.

Name | Description | Default
-- | -- | --
`MEMBERAUDIT_APP_NAME`| Name of this app as shown in the Auth sidebar. | `'Member Audit'`
`MEMBERAUDIT_DATA_RETENTION_LIMIT`| Maximum number of days to keep historical data for mails, contracts and wallets. Minimum is 7 day. `None` will turn it off. | `360`
`MEMBERAUDIT_ESI_ERROR_LIMIT_THRESHOLD`| ESI error limit remain threshold. The number of remaining errors is counted down from 100 as errors occur. Because multiple tasks may request the value simultaneously and get the same response, the threshold must be above 0 to prevent the API from shutting down with a 420 error | `25`
`MEMBERAUDIT_BULK_METHODS_BATCH_SIZE`| Technical parameter defining the maximum number of objects processed per run of Django batch methods, e.g. bulk_create and bulk_update | `500`
`MEMBERAUDIT_LOCATION_STALE_HOURS`| Hours after a existing location (e.g. structure) becomes stale and gets updated. e.g. for name changes of structures | `24`
`MEMBERAUDIT_LOG_UPDATE_STATS`| When set True will log the statistics of the latests uns at the start of every new run. The stats show the max, avg, min durations from the last run for each round and each section in seconds. Note that the durations are not 100% exact, because some updates happen in parallel the the main process and may take longer to complete (e.g. loading mail bodies, contract items) | `24`
`MEMBERAUDIT_MAX_MAILS`| Maximum amount of mails fetched from ESI for each character | `250`
`MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS`| Technical parameter defining the maximum number of asset items processed in each pass when updating character assets. A higher value reduces overall duration, but also increases task queue congestion. | `2500`
`MEMBERAUDIT_TASKS_TIME_LIMIT`| Global timeout for tasks in seconds to reduce task accumulation during outages | `7200`
`MEMBERAUDIT_UPDATE_STALE_RING_1`| Minutes after which sections belonging to ring 1 are considered stale: location, online status | `55`
`MEMBERAUDIT_UPDATE_STALE_RING_2`| Minutes after which sections belonging to ring 2 are considered stale: all except those in ring 1 & 3 | `235`
`MEMBERAUDIT_UPDATE_STALE_RING_3`| Minutes after which sections belonging to ring 3 are considered stale: assets | `475`

## Management Commands

The following management commands are available to perform administrative tasks:

> **Hint**:<br>Run any command with `--help` to see all options

### memberaudit_load_eve

Pre-loads data required for this app from ESI to improve app performance.

### memberaudit_reset_characters

This command deletes all locally stored character data, but maintains character skeletons, so they can be reloaded again from ESI.

> **Warning**<br>Make sure to stop all supervisors before using this command.

### memberaudit_stats

This command returns current statistics as JSON, i.e. current update statistics and app totals. This includes:

- App totals with number of active users and characters
- List of periodic celery tasks
- Statistics about last update per ring, including:
  - total duration
  - est. throughput in characters per hour
  - indicator if update was completed within time boundaries

### memberaudit_update_characters

Start the process of force updating all characters from ESI.

## Authors

The main authors (in alphabetical order):

- [Erik Kalkoken](https://gitlab.com/ErikKalkoken)
- [Rebecca Claire Murphy](https://gitlab.com/rcmurphy), aka Myrhea
- [Peter Pfeufer](https://gitlab.com/ppfeufer), aka Rounon Dax
