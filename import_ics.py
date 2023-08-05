#!/usr/bin/env python3
import json
import os
import re
import sys
import tomllib
import uuid
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from icalendar import Calendar, Event

from cache import JSONCache

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


class Strategy(Enum):
    OUR = auto()
    UPSTREAM = auto()
    NEWER = auto()
    MERGE_OUR = auto()
    MERGE_UPSTREAM = auto()


class MergeStrategy:
    def __init__(self, value: str):
        value = value.lower().strip()
        if value == "our":
            self.strategy = Strategy.OUR
        elif value == "upstream":
            self.strategy = Strategy.UPSTREAM
        elif value == "newer":
            self.strategy = Strategy.NEWER
        elif value == "merge,our":
            self.strategy = Strategy.MERGE_OUR
        elif value == "merge,upstream":
            self.strategy = Strategy.MERGE_UPSTREAM
        else:
            raise ValueError("No such merge strategy " + value)

    @staticmethod
    def __select_newer_event__(our: Event, upstream: Event) -> Event:
        if our["LAST-MODIFIED"] < upstream["LAST_MODIFIED"]:
            return upstream
        else:
            return our

    def __merge_events__(
        self,
        base_event: Event,
        local: Event,
        upstream: Event,
    ):
        merged_event = Event()
        print("Location local:", local.get("LOCATION"))
        print("Location upstream:", upstream.get("LOCATION"))
        print("Location base:", base_event.get("LOCATION"))
        all_keys = set(base_event.keys()) | set(local.keys()) | set(upstream.keys())
        for prop in all_keys:
            if prop == "LAST-MODIFIED":
                merged_event.add("LAST-MODIFIED", datetime.now())
                continue
            if local.get(prop) == upstream.get(prop) == base_event.get(prop):
                merged_event[prop] = base_event.get(prop)
            elif local.get(prop) == upstream.get(prop):
                merged_event[prop] = local.get(prop)
            elif local.get(prop) == base_event.get(prop):
                if prop in upstream:
                    merged_event[prop] = upstream.get(prop)
            elif upstream.get(prop) == base_event.get(prop):
                if prop in local:
                    merged_event[prop] = local.get(prop)
            elif prop not in local:
                merged_event[prop] = upstream.get(prop)
            elif prop not in upstream:
                merged_event[prop] = local.get(prop)
            else:
                # CONFLICT
                if self.strategy == Strategy.MERGE_UPSTREAM:
                    print("up", upstream.get(prop))
                    merged_event[prop] = upstream.get(prop)
                elif self.strategy == Strategy.MERGE_OUR:
                    print("local", local.get(prop))
                    merged_event[prop] = local.get(prop)
                else:
                    raise NotImplementedError
        return merged_event

    def apply(
        self,
        upstream: Event,
        existing: Event,
        original_version: Event,
    ):
        if self.strategy == Strategy.OUR:
            return None
        if self.strategy == Strategy.UPSTREAM:
            return upstream
        elif self.strategy == Strategy.NEWER:
            newer = self.__select_newer_event__(existing, upstream)
            return newer
        elif self.strategy in [Strategy.MERGE_UPSTREAM, Strategy.MERGE_OUR]:
            print(existing)
            merged = self.__merge_events__(
                base_event=original_version, local=existing, upstream=upstream
            )
            return merged
        else:
            raise NotImplementedError()


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


def main():
    cache = JSONCache(APP_NAME)
    try:
        with open(search_config_file(), "rb") as f:
            conf = tomllib.load(f)
    except FileNotFoundError:
        print("No configuration found")
        sys.exit(1)
    try:
        user = conf["user"]
    except KeyError as e:
        print(f'Invalid configuration, missing paramerter "{e.args[0]}"')
        sys.exit(2)
    for project, p_config in conf.items():
        if project == "user":
            continue
        try:
            url = p_config["url"]
            cal_id = p_config["cal_id"]
            strategy = MergeStrategy(p_config["strategy"])
        except KeyError as e:
            print(
                f'Invalid configuration, missing paramerter "{e.args[0]}" for project "{project}"'
            )
            sys.exit(2)
        filter_list = p_config.get("filter", {})
        user_folder = Path.home() / "collections/collection-root" / user
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
