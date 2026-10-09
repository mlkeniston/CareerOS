from __future__ import annotations

from dataclasses import dataclass

CONNECTION_NOTE_MAX_LENGTH = 200


class InvalidOutreachDraft(ValueError):
    pass


@dataclass(slots=True)
class OutreachMessage:
    connection_note: str
    follow_up_message: str
    evidence: list[str]

    @classmethod
    def parse(cls, value: object) -> "OutreachMessage":
        if not isinstance(value, dict):
            raise InvalidOutreachDraft("Outreach response must be a JSON object")
        note = value.get("connection_note")
        follow_up = value.get("follow_up_message")
        evidence = value.get("evidence")
        if not isinstance(note, str) or not note.strip() or len(note) > CONNECTION_NOTE_MAX_LENGTH:
            raise InvalidOutreachDraft("Outreach response has an invalid connection note")
        if not isinstance(follow_up, str) or not follow_up.strip() or len(follow_up) > 8000:
            raise InvalidOutreachDraft("Outreach response has an invalid follow-up message")
        if not isinstance(evidence, list) or len(evidence) > 12 or not all(
            isinstance(item, str) and 1 <= len(item.strip()) <= 500 for item in evidence
        ):
            raise InvalidOutreachDraft("Outreach response has invalid evidence notes")
        return cls(note.strip(), follow_up.strip(), [item.strip() for item in evidence])


@dataclass(slots=True)
class OutreachDraft:
    id: str
    job_id: str
    resume_id: str
    task_id: str | None
    status: str
    draft: dict | None
    updated_at: str
