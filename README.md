# aa-memberaudit

**!! This app is in development and not ready yet for production. !!**

An app for auditing members on Alliance Auth

![release](https://img.shields.io/pypi/v/aa-memberaudit?label=release) ![python](https://img.shields.io/pypi/pyversions/aa-memberaudit) ![django](https://img.shields.io/pypi/djversions/aa-memberaudit?label=django) ![pipeline](https://gitlab.com/ErikKalkoken/aa-memberaudit/badges/master/pipeline.svg) ![coverage](https://gitlab.com/ErikKalkoken/aa-memberaudit/badges/master/coverage.svg) ![license](https://img.shields.io/badge/license-MIT-green) ![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)

## Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Updating](#updating)
- [Permissions](#permissions)
- [Settings](#settings)
- [Management Commands](#management-commands)
- [Change Log](CHANGELOG.md)

## Overview

Member Audit provides a way for recruiters and alliance leadership to inspect characters' ESI data. It supports generating reports showing whether a given user has registered all their characters with Member Audit and whether they can fly doctrine ships. It also allows users to view all their characters ESI data, and allows for selectively sharing character data with recruiters.

## Key Features

Member Audit adds the following key features to Auth:

- Users can see an overview of all their characters with key information like current location and wallet balance
- Users can see many details about their characters without having to log into Eve (e.g. wallet, mails, assets, ...)
- Recruiters can see characters of applicants for vetting
- Leadership can see characters of their members for auditing (e.g. to check suspicious members)
- Leadership can see reports and analytics about their members (e.g. which members can fly certain doctrines)
- Users are assigned to a group automatically based on compliance
- More features will be added soon

## Screenshots

### Character Launcher

The main page for users to register their characters and get a key infos of all registered characters.

![launcher](https://i.imgur.com/v9AU3Gr.jpg)

### Character Viewer

The page for displaying all details about a character.

![viewer](https://i.imgur.com/vo1N3kg.jpg)

### Doctrines

This tab on the character view allows you to view what fittings a character can or can't fly. For ships they can't fly, it also shows what skills are missing.

![doctrines](https://i.imgur.com/ATlExgl.jpg)

 Skill requirements can be customized per ship in the administration panel.

![doctrine-admin](https://i.imgur.com/nUp7ffV.jpg)

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

### Step 2 - Configure settings

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

This app makes heavy use of Celery and will typically run through many thousands of tasks with every character update run. Auth's default process based setup for Celery workers is sadly not well suited for high task volume and we therefore strongly recommend to switch to a thread based setup (e.g. gevent). A thread based setup allows you to run 5-10x more workers in parallel, significantly reducing the duration of character update runs.

For details on how to configure a celery workers with threads please check [this section](https://allianceauth.readthedocs.io/en/latest/maintenance/tuning/celery.html#increasing-task-throughput) in the Auth's documentation.

Note that if you have more than 10 workers you also need to increase the connection pool for django-esi accordingly. See [here](https://gitlab.com/allianceauth/django-esi/-/blob/master/esi/app_settings.py#L32) for the corresponding setting.

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

### Overview

For this app there are two types of permissions:

- Feature permissions give access to a feature
- Scope permissions give access to scope

To define a role you will mostly need at least one permission from each type. For example for the recruiter role you will want `finder_access`, that gives access to the character finder tool, and `view_shared_characters`, so that the recruiter can see all shared characters.

The exception is the basic role, `basic_access`, that every user needs just to access the app. It does not require any additional scope roles, so a normal user just needs that role to be able to register his characters.

### Permission list

Name | Description | Type
-- | -- | --
`basic_access`| Can access this app and register and view own characters | Feature
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

## Settings

Here is a list of available settings for this app. They can be configured by adding them to your AA settings file (`local.py`).

Note that all settings are optional and the app will use the documented default settings if they are not used.

Name | Description | Default
-- | -- | --
`MEMBERAUDIT_APP_NAME`| Name of this app as shown in the Auth sidebar. | `'Member Audit'`
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

### memberaudit_statistics

This command returns current statistics as JSON, i.e. current update statistics.

### memberaudit_update_characters

Start the process of force updating all characters from ESI.
