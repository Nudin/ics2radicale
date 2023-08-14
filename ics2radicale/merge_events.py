from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional

from icalendar import Event


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
