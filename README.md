# aa-memberaudit

**!! This app is in development and not ready yet for production. !!**

An app for auditing members on Alliance Auth

![release](https://img.shields.io/pypi/v/aa-memberaudit?label=release) ![python](https://img.shields.io/pypi/pyversions/aa-memberaudit) ![django](https://img.shields.io/pypi/djversions/aa-memberaudit?label=django) ![pipeline](https://gitlab.com/ErikKalkoken/aa-memberaudit/badges/master/pipeline.svg) ![coverage](https://gitlab.com/ErikKalkoken/aa-memberaudit/badges/master/coverage.svg) ![license](https://img.shields.io/badge/license-MIT-green) ![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)

## Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Permissions](#permissions)
- [Settings](#settings)
- [Change Log](CHANGELOG.md)

## Overview

Memberaudit adds the following key features to Auth:

- Users can see an overview of all their characters with key information like current location and wallet balance
- Users can see many details about their characters without having to log into Eve (e.g. wallet, mails, assets, ...)
- Recruiters can see characters of applicants for vetting
- Leadership can see characters of their members for auditing (e.g. to check suspicious members)
- Leadership can see reports and analytics about their members (e.g. which members can fly certain doctrines)

## Key Features

tbd.

## Screenshots

### Character Launcher

The main page for users to register their characters and get a key infos of all registered characters.

![launcher](https://i.imgur.com/LdILg1X.png)

### Character Viewer

The page for displaying all details about a character.

![viewer](https://i.imgur.com/9kGi6dJ.png)

### Character Finder

On this page recruiters and leadership can look for other characters to view (assuming they have been given permission).

![finder](https://i.imgur.com/Uzv07uy.png)

## Installation

### Preconditions

1. Memberaudit is a plugin for Alliance Auth. If you don't have Alliance Auth running already, please install it first before proceeding. (see the official [AA installation guide](https://allianceauth.readthedocs.io/en/latest/installation/auth/allianceauth/) for details)

2. Memberaudit needs the app [django-eveuniverse](https://gitlab.com/ErikKalkoken/django-eveuniverse) to function. Please make sure it is installed, before before continuing.

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
CELERYBEAT_SCHEDULE['memberaudit_update_all_characters'] = {
    'task': 'memberaudit.tasks.update_all_characters',
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

### Step 4 - Verify Celery configuration

This app makes heavy use of Celery and will typically run through many thousands of tasks with every character update run. Auth's default process based setup for Celery workers is sadly not well suited for high task volume and we therefore strongly recommend to switch to a thread based setup (e.g. gevent). A thread based setup allows you to run 5-10x more workers in parallel, significantly reducing the duration of character update runs.

For details on how to configure a celery workers with threads please check [this section](https://allianceauth.readthedocs.io/en/latest/maintenance/tuning/celery.html#increasing-task-throughput) in the Auth's documentation.

Note that if you have more than 10 workers you also need to increase the connection pool for django-esi accordingly. See [here](https://gitlab.com/allianceauth/django-esi/-/blob/master/esi/app_settings.py#L32) for the corresponding setting.

### Step 5 - Load Eve Universe map data

In order to be able to select solar systems and ships types for trackers you need to load that data from ESI once. If you already have run those commands previously you can skip this step.

Load Eve Online map:

```bash
python manage.py eveuniverse_load_data map
```

```bash
python manage.py memberaudit_load_eve
```

You may want to wait until the loading is complete before starting to create new trackers.

### Step 6 - Setup permissions

Finally you want to setup permission to define which users / groups will have access to which parts of the app. Check out [permissions](#permissions) for details.

Congratulations you are now ready to use memberaudit!

## Permissions

For this app there are two types of permissions:

- Feature permissions give access to a feature
- Scope permissions give access to scope

To define a role you will mostly need at least one permission from each type. For example for the recruiter role you will want `finder_access`, that gives access to the character finder tool, and `view_shared_characters, so that the recruiter can see all shared characters.

The exception is the basic role, `basic_access`, that every user needs just to access the app. It does not require any additional scope roles, so a normal user just needs that role to be able to register his characters.

Name | Description | Type
-- | -- | --
`basic_access`| Can access this app and register and view his characters | Feature
`finder_access`| Can access character finder features for accessing characters from others | Feature
`reports_access`| Can access reports features for seeing reports and analytics. | Feature
`view_shared_characters`| Can view characters that have been marked as shared | Scope
`view_same_corporation`| Can view characters and data of his main's corporation | Scope
`view_same_alliance`| Can view characters and data of his main's alliance | Scope
`view_everything`| Can view all characters and data. This scope role is equivalent with superuser access. Use it with care. | Scope

Note that all relevant permissions are under the sub-category "general".

## Settings

Here is a list of available settings for this app. They can be configured by adding them to your AA settings file (`local.py`).

Note that all settings are optional and the app will use the documented default settings if they are not used.

Name | Description | Default
-- | -- | --
`MEMBERAUDIT_BULK_METHODS_BATCH_SIZE`| Technical parameter defining the maximum number of objects processed per run of Django batch methods, e.g. bulk_create and bulk_update | `500`
`MEMBERAUDIT_LOCATION_STALE_HOURS`| Hours after a existing location (e.g. structure) becomes stale and gets updated. e.g. for name changes of structures | `24`
`MEMBERAUDIT_MAX_MAILS`| Maximum amount of mails fetched from ESI for each character | `250`
`MEMBERAUDIT_TASKS_MAX_ASSETS_PER_PASS`| Technical parameter defining the maximum number of asset items processed in each pass when updating character assets. A higher value reduces duration, but also increases task queue congestion | `250`
`MEMBERAUDIT_TASKS_TIME_LIMIT`| Global timeout for tasks in seconds to reduce task accumulation during outages | `7200`
`MEMBERAUDIT_UPDATE_STALE_RING_1`| Minutes after which sections belonging to ring 1 are considered stale: location, online status | `60`
`MEMBERAUDIT_UPDATE_STALE_RING_2`| Minutes after which sections belonging to ring 2 are considered stale: all except those in ring 1 & 3 | `240`
`MEMBERAUDIT_UPDATE_STALE_RING_3`| Minutes after which sections belonging to ring 3 are considered stale: assets | `480`
