from datetime import datetime, timedelta, timezone

from careeros.autopilot.scheduler import AutopilotScheduler
from careeros.autopilot.state import AutopilotState
from careeros.queue import TaskQueue


def test_first_discovery_is_queued_once_and_can_repeat_after_six_hours(db):
    queue = TaskQueue(db)
    scheduler = AutopilotScheduler(db, queue)
    first_time = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    first_id = scheduler.maybe_enqueue_discovery(first_time)

    assert first_id is not None
    first = queue.get(first_id)
    assert (first.kind, first.provider, first.cloud_confirmed, first.status) == (
        "job_discovery", "ollama", False, "queued"
    )
    assert scheduler.maybe_enqueue_discovery(first_time + timedelta(seconds=1)) is None

    claimed = queue.claim_next({"job_discovery"})
    queue.finish(claimed.id, {"jobs_found": 3})
    second_id = scheduler.maybe_enqueue_discovery(first_time + timedelta(hours=6))

    assert second_id is not None
    assert second_id != first_id


def test_scheduler_does_not_duplicate_a_queued_or_running_discovery(db):
    queue = TaskQueue(db)
    scheduler = AutopilotScheduler(db, queue)
    first_time = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    first_id = scheduler.maybe_enqueue_discovery(first_time)
    assert scheduler.maybe_enqueue_discovery(first_time + timedelta(hours=6)) is None

    claimed = queue.claim_next({"job_discovery"})
    assert claimed.id == first_id
    assert scheduler.maybe_enqueue_discovery(first_time + timedelta(hours=12)) is None


def test_autopilot_pause_persists_across_state_instances(db):
    state = AutopilotState(db)

    assert state.set_enabled(False)["enabled"] is False
    assert AutopilotState(db).get()["enabled"] is False
