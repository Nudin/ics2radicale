from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from icalendar import Event, vCalAddress, vText
from import_ics import merge_events


def create_demo_event():
    # Create a new Event object
    event = Event()

    # Fill in the most common fields of the event
    event.add("SUMMARY", "Business Meeting")

    # Set start and end time as datetime objects (in the example, +1 hour)
    start_time = datetime(2023, 8, 1, 12, 0, 0)
    end_time = start_time + timedelta(hours=1)

    event.add("DTSTART", start_time)
    event.add("DTEND", end_time)

    event.add("LOCATION", "Conference Room A")
    event.add("DESCRIPTION", "An important business meeting with clients.")

    # Add attendees (Optional)
    organizer = vCalAddress("MAILTO:organizer@example.com")
    organizer.params["cn"] = vText("Max Mustermann")
    event["ORGANIZER"] = organizer

    attendee1 = vCalAddress("MAILTO:attendee1@example.com")
    attendee1.params["cn"] = vText("Attendee 1")
    event["ATTENDEE"] = attendee1

    attendee2 = vCalAddress("MAILTO:attendee2@example.com")
    attendee2.params["cn"] = vText("Attendee 2")
    event["ATTENDEE"] = attendee2

    # Recurring events (Optional)
    event.add("RRULE", {"FREQ": "WEEKLY", "COUNT": 5})  # Create 5 recurring events

    return event


base_event = create_demo_event()


def test_merge_three_way_no_changes():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event == base_event
    assert merged_event == local_event
    assert merged_event == remote_event


def test_merge_three_way_only_local_changed():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    local_event["SUMMARY"] = "Altered"
    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event != base_event
    assert merged_event == local_event
    assert merged_event != remote_event
    assert merged_event["SUMMARY"] == "Altered"


def test_merge_three_way_local_and_remote_changed_identically():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    local_event["SUMMARY"] = "Altered"
    remote_event["SUMMARY"] = "Altered"
    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event != base_event
    assert merged_event == local_event
    assert merged_event == remote_event
    assert merged_event["SUMMARY"] == "Altered"


def test_merge_three_way_only_remote_changed():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    remote_event["SUMMARY"] = "Altered"
    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event != base_event
    assert merged_event != local_event
    assert merged_event == remote_event
    assert merged_event["SUMMARY"] == "Altered"


def test_merge_three_way_different_fields_changed():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    local_event["LOCATION"] = "Berlin"
    remote_event["SUMMARY"] = "Altered"
    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event != base_event
    assert merged_event != local_event
    assert merged_event != remote_event
    assert merged_event["SUMMARY"] == "Altered"
    assert merged_event["LOCATION"] == "Berlin"


def test_merge_three_way_with_conflict():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    local_event["SUMMARY"] = "Altered"
    local_event["LOCATION"] = "Berlin"
    remote_event["LOCATION"] = "New York"

    # Exception without a preference defined
    with pytest.raises(ValueError):
        merge_events(base_event, remote_event, local_event)

    # Use the local_event preference value
    merged_event = merge_events(base_event, remote_event, local_event, local_event)
    assert merged_event != base_event
    assert merged_event != local_event
    assert merged_event != remote_event
    assert merged_event["SUMMARY"] == "Altered"
    assert merged_event["LOCATION"] == "Berlin"

    # Use the remote_event preference value
    merged_event = merge_events(base_event, remote_event, local_event, remote_event)
    assert merged_event != base_event
    assert merged_event != local_event
    assert merged_event != remote_event
    assert merged_event["SUMMARY"] == "Altered"
    assert merged_event["LOCATION"] == "New York"


def test_merge_three_way_new_fields():
    local_event = deepcopy(base_event)
    remote_event = deepcopy(base_event)

    local_event["NEW"] = "NEW"
    remote_event["NEW2"] = "NEW2"
    merged_event = merge_events(base_event, remote_event, local_event)
    assert merged_event != base_event
    assert merged_event != local_event
    assert merged_event != remote_event
    assert merged_event["NEW"] == "NEW"
    assert merged_event["NEW2"] == "NEW2"
    for prop in base_event:
        assert local_event[prop] == remote_event[prop] == base_event[prop]
