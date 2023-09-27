import logging
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import icalendar
from icalendar import Event


def unpack_value(elemtent):
    if isinstance(elemtent, icalendar.prop.vDDDTypes):
        return elemtent.dt
    elif isinstance(elemtent, icalendar.prop.vCategory):
        return [str(e) for e in elemtent.cats]
    elif isinstance(elemtent, icalendar.cal.Event):
        return {x: unpack_value(y) for x, y in elemtent.items()}
    elif isinstance(elemtent, icalendar.prop.vText):
        return str(elemtent)
    elif type(elemtent).__module__.split(".")[0] == "icalendar":
        logging.debug("Element type not properly implemented: %s", type(elemtent))
        return elemtent.to_ical()
    else:
        return elemtent


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
        if unpack_value(base_event) == unpack_value(local) == unpack_value(upstream):
            return base_event
        merged_event = Event()
        logging.info(
            f"Merging event {local.get('summary')} and {upstream.get('summary')}"
        )
        all_keys = set(base_event.keys()) | set(local.keys()) | set(upstream.keys())
        for prop in all_keys:
            if prop == "LAST-MODIFIED":
                merged_event.add("LAST-MODIFIED", datetime.now())
                continue
            local_prop = local.get(prop)
            local_val = unpack_value(local_prop)
            upstream_prop = upstream.get(prop)
            upstream_val = unpack_value(upstream_prop)
            base_prop = base_event.get(prop)
            base_val = unpack_value(base_prop)
            if local_val == upstream_val == base_val:
                merged_event[prop] = base_prop
            elif local_val == upstream_val:
                merged_event[prop] = local_prop
            elif local_val == base_val:
                if prop in upstream:
                    merged_event[prop] = upstream_prop
            elif upstream_val == base_val:
                if prop in local:
                    merged_event[prop] = local_prop
            elif prop not in local:
                merged_event[prop] = upstream_prop
            elif prop not in upstream:
                merged_event[prop] = local_prop
            else:
                # CONFLICT
                if self.strategy == Strategy.MERGE_UPSTREAM:
                    logging.info(
                        "Conflict, use upstream %s=%s",
                        prop,
                        upstream_val,
                    )
                    logging.debug("Overwriting old value %s=%s", prop, local_val)
                    merged_event[prop] = upstream_prop
                elif self.strategy == Strategy.MERGE_OUR:
                    logging.info("Conflict, use local %s=%s", prop, local_val)
                    logging.debug(
                        "Ignoring upstream value %s=%s",
                        prop,
                        upstream_val,
                    )
                    merged_event[prop] = local_prop
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
            merged = self.__merge_events__(
                base_event=original_version, local=existing, upstream=upstream
            )
            return merged
        else:
            raise NotImplementedError()
