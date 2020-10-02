# aa-memberaudit

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

xxx

## Key Features

- Management reports based on character data to inform decisions
- Recruiters can access characters of potential recruits
- Members can access data about their characters through Auth

## Screenshots

xx

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
    'schedule': crontab(hour='*/4'),
}
```

- Optional: Add additional settings if you want to change any defaults. See [Settings](#settings) for the full list.

### Step 3 - Finalize installation

Run migrations & copy static files

```bash
python manage.py migrate
python manage.py collectstatic
```

Restart your supervisor services for Auth

### Step 4 - Load Eve Universe map data

In order to be able to select solar systems and ships types for trackers you need to load that data from ESI once. If you already have run those commands previously you can skip this step.

Load Eve Online map:

```bash
python manage.py eveuniverse_load_data map
```

```bash
python manage.py memberaudit_load_eve
```

You may want to wait until the loading is complete before starting to create new trackers.

### Step 5 - Setup permissions

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
`MEMBERAUDIT_MAX_MAILS`| Maximum amount of mails fetched from ESI for each character | `250`
