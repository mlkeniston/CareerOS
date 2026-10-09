from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class PlannerRequest:
    task: str
    instruction: str


@dataclass(slots=True)
class PlannerResult:
    text: str
    files: list[dict] = field(default_factory=list)


class Planner(Protocol):
    def generate(self, request: PlannerRequest) -> PlannerResult: ...
