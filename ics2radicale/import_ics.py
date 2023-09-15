#!/usr/bin/env python3
import json
import os
import re
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any, Dict

import requests
from icalendar import Calendar, Event

from .cache import JSONCache
from .merge_events import MergeStrategy

APP_NAME = "ics2radicale"


def event2Calendar(event: Event) -> Calendar:
    cal = Calendar()
    cal.add_component(event)
    return cal


def search_calendar(user_path, name):
    for feed in user_path.iterdir():
        if not feed.is_dir():
            continue
        props_file = feed / ".Radicale.props"
        props = json.loads(props_file.read_text())
        if props.get("D:displayname") == name:
            return feed
    return None


def create_calendar(user_path, name):
    cal_id = uuid.uuid4()
    cal_path = user_path / str(cal_id)
    props_file = cal_path / ".Radicale.props"
    data = {
        "C:supported-calendar-component-set": "VEVENT",
        "D:displayname": name,
        "tag": "VCALENDAR",
    }
    cal_path.mkdir(parents=True, exist_ok=True)
    props_file.write_text(json.dumps(data))
    return cal_path


def apply_operator(value1: Any, value2: Any, operator: str) -> bool:
    try:
        if operator == "==":
            return value1 == value2
        elif operator == "!=":
            return value1 != value2
        elif operator == "in":
            return value1 in value2
        elif operator == "not in":
            return value1 not in value2
        elif operator == "match":
            return bool(re.match(value2, value1))
        elif operator == "not match":
            return not bool(re.match(value2, value1))
        else:
            raise ValueError(
                "Invalid operator. Supported operators are "
                + "'==', '!=', 'in', 'not in', 'match', and 'not match'."
            )
    except TypeError:
        raise ValueError(  # pylint: disable=raise-missing-from
            "Cannot apply the operator to the given values."
        )


def filter_event(event: Event, filter_list: Dict[str, Dict[str, str]]):
    remove_event = None
    for test in filter_list.values():
        field = test.get("field", "SUMMARY")
        operator = test.get("operator", "==")
        action = test.get("action", "remove")
        if "value" not in test:
            raise ValueError(  # pylint: disable=raise-missing-from
                "Missing filter parameter"
            )
        value = test["value"]
        if field not in event:
            continue
        field_value = event[field]
        if apply_operator(value, field_value, operator):
            # If there is a remove and a keep filter, the keep wins
            if action == "remove" and remove_event is None:
                remove_event = True
            elif action == "keep":
                remove_event = False
            elif action == "set":
                action_field = test["action_field"]
                action_value = test["action_value"]
                event[action_field] = action_value
            else:
                raise ValueError("Unsupported action", action)
    if remove_event:
        return None
    return event


def process_event(event, folder, strategy, filter_list, cache):
    uid = str(event["UID"])
    filename = folder / (uid + ".ics")

    # Apply filters
    # TODO: decide if existing events should be removed if filtered?
    event = filter_event(event, filter_list)
    if event is None:
        print("Remove event")
        return

    # Check if event is already present
    if filename.exists():
        try:
            original_version = Event.from_ical(cache.get(uid))
            existing = Calendar.from_ical(filename.read_text()).subcomponents[0]
            event = strategy.apply(
                upstream=event,
                existing=existing,
                original_version=original_version,
            )
            if event == existing:
                return  # no need to do anything
        except ValueError as e:
            print("Warning: Could not apply merge strategy")
            print(" Exception was: ", e)
        if event is None:
            return
    elif uid in cache:  # Event was deleted by user, skip it
        return

    # Hack: remove all carriage returns, since they break radicale
    for field_name, field in event.items():
        if isinstance(field, str):
            event[field_name] = field.replace("\r", "")

    cache.set(uid, event.to_ical().decode())
    with open(filename, "wb") as f:
        f.write(event2Calendar(event).to_ical())


def process_cal(url: str, folder: Path, strategy: MergeStrategy, filter_list, cache):
    req = requests.get(url=url, timeout=10)
    if req.status_code != 200:
        raise ConnectionError(req.status_code, req.text)
    req.encoding = "UTF-8"  # FIXME (dirty fix for broken encoding by on server)

    calendar = Calendar.from_ical(req.text)
    for event in calendar.subcomponents:
        if event.name == "VEVENT":
            process_event(event, folder, strategy, filter_list, cache)
        else:
            print(f"WARNING: Component not implemented: {event.name}, skipping")
            continue


def search_config_file():
    # Check XDG environment variables
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
    xdg_config_file = xdg_config_home / APP_NAME / "config.toml"
    if xdg_config_file.exists():
        return xdg_config_file

    # Check home directory
    home_dir = Path.home()
    home_config_file = home_dir / f".{APP_NAME}.toml"
    if home_config_file.exists():
        return home_config_file

    # Check working directory
    cwd = Path.cwd()
    home_config_file = cwd / "config.toml"
    if home_config_file.exists():
        return home_config_file

    # If the configuration file is not found in any of the common locations
    raise FileNotFoundError("Configuration could not be found")


class Config:
    def __init__(self):
        try:
            with open(search_config_file(), "rb") as f:
                self.conf = tomllib.load(f)
        except FileNotFoundError:
            print("No configuration found")
            sys.exit(1)
        try:
            self.user = self.conf["user"]
        except KeyError as e:
            print(f'Invalid configuration, missing paramerter "{e.args[0]}"')
            sys.exit(2)

        self.projects = {}
        for project, p_config in self.conf.items():
            if project == "user":
                continue
            try:
                self.projects[project] = p_config
                _ = p_config["url"]
                _ = p_config["cal_id"]
                self.projects[project]["strategy"] = MergeStrategy(p_config["strategy"])
            except KeyError as e:
                print(
                    f'Invalid configuration, missing paramerter "{e.args[0]}" for project "{project}"'
                )
                sys.exit(2)


def main():
    cache = JSONCache(APP_NAME)
    conf = Config()
    for project, p_config in conf.projects.items():
        url = p_config["url"]
        cal_id = p_config["cal_id"]
        filter_list = p_config.get("filter", {})
        user_folder = Path.home() / "collections/collection-root" / conf.user
        strategy = p_config["strategy"]
        if cal_id == "auto":
            folder = search_calendar(user_folder, project)
            if folder is None:
                print(f"Error: could not find calendar {project}")
                print(
                    "Hint: use cal_id='auto,create' to create new calendar or specify calendar id"
                )
                continue
        elif cal_id == "auto,create":
            folder = search_calendar(user_folder, project)
            if folder is None:
                folder = create_calendar(user_folder, project)
        else:
            folder = user_folder / cal_id
        project_cache = cache.get_subcache(project)
        process_cal(url, folder, strategy, filter_list, project_cache)


if __name__ == "__main__":
    main()
