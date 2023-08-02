#!/usr/bin/env python3
import re
import sys
import tomllib
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from icalendar import Calendar, Event

from cache import JSONCache


def event2Calendar(event: Event) -> Calendar:
    cal = Calendar()
    cal.add_component(event)
    return cal


class MergeStrategy(Enum):
    OUR = auto()
    UPSTREAM = auto()
    NEWER = auto()
    MERGE_OUR = auto()
    MERGE_UPSTREAM = auto()

    @classmethod
    def parse(cls, value: str):
        value = value.lower().strip()
        if value == "our":
            return cls.OUR
        if value == "upstream":
            return cls.UPSTREAM
        if value == "newer":
            return cls.NEWER
        if value == "merge,our":
            return cls.MERGE_OUR
        if value == "merge,upstream":
            return cls.MERGE_UPSTREAM
        raise ValueError("No such merge strategy " + value)


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


def select_newer_event(our: Event, upstream: Event) -> Event:
    if our["LAST-MODIFIED"] < upstream["LAST_MODIFIED"]:
        return upstream
    else:
        return our


def merge_events(
    base_event: Event, local: Event, upstream: Event, preference: Optional[Event] = None
):
    merged_event = Event()
    all_keys = set(base_event.keys()) | set(local.keys()) | set(upstream.keys())
    for prop in all_keys:
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
            merged_event[prop] = upstream
        elif prop not in upstream:
            merged_event[prop] = local
        else:
            # CONFLICT
            if preference is None:
                raise ValueError("CONFLICT on merging event", base_event)
            merged_event[prop] = preference.get(prop)
    return merged_event


def apply_merge_strategy(
    strategy: MergeStrategy, upstream: Event, existing: Event, original_version: Event
):
    if strategy == MergeStrategy.OUR:
        return None
    if strategy == MergeStrategy.UPSTREAM:
        return upstream
    elif strategy == MergeStrategy.NEWER:
        existing = existing.subcomponents[0]
        newer = select_newer_event(existing, upstream)
        if newer == existing:
            return None
        return newer
    elif strategy == MergeStrategy.MERGE_UPSTREAM:
        existing = existing.subcomponents[0]
        merged = merge_events(original_version, existing, upstream, upstream)
        if merged == existing:
            return None
        return merged
    elif strategy == MergeStrategy.MERGE_OUR:
        existing = existing.subcomponents[0]
        merged = merge_events(original_version, existing, upstream, existing)
        if merged == existing:
            return None
        return merged
    else:
        raise NotImplementedError()


def filter_event(event: Event, filter_list: Dict[str, Dict[str, str]]):
    remove_event = False
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
            if action == "remove":
                remove_event = True
            elif action == "keep":
                remove_event = False
            else:
                raise ValueError("Unsupported action", action)
    return remove_event


def process_cal(url: str, folder: Path, strategy: MergeStrategy, filter_list, cache):
    req = requests.get(url=url, timeout=10)
    if req.status_code != 200:
        raise ConnectionError(req.status_code, req.text)

    calendar = Calendar.from_ical(req.text)
    for event in calendar.subcomponents:
        if event.name != "VEVENT":
            raise NotImplementedError("Component not implemented: " + event.name)

        uid = str(event["UID"])
        filename = folder / (uid + ".ics")

        # Apply filters
        # TODO: decide if existing events should be removed if filtered?
        if filter_event(event, filter_list):
            continue

        # Check if event is already present
        if filename.exists():
            original_version = Event.from_ical(cache.get(uid))
            existing = Calendar.from_ical(filename.read_text())
            event = apply_merge_strategy(
                strategy=strategy,
                upstream=event,
                existing=existing,
                original_version=original_version,
            )
            if event is None:
                continue

        cache.set(uid, event.to_ical().decode())
        with open(filename, "wb") as f:
            f.write(event2Calendar(event).to_ical())


def main():
    cache = JSONCache("import_ics")
    try:
        with open("config.toml", "rb") as f:
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
            strategy = MergeStrategy.parse(p_config["strategy"])
        except KeyError as e:
            print(
                f'Invalid configuration, missing paramerter "{e.args[0]}" for project "{project}"'
            )
            sys.exit(2)
        filter_list = p_config.get("filter", {})
        folder = Path.home() / "collections/collection-root" / user / cal_id
        project_cache = cache.get_subcache(project)
        process_cal(url, folder, strategy, filter_list, project_cache)


if __name__ == "__main__":
    main()
