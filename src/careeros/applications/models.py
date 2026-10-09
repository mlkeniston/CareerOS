from dataclasses import dataclass


class InvalidPlannerOutput(ValueError):
    pass


@dataclass(slots=True)
class ApplicationDraft:
    cover_letter: str
    resume_alignment: list[str]
    answers: dict[str, str]
    next_steps: list[str]

    @classmethod
    def parse(cls, value: object) -> "ApplicationDraft":
        if not isinstance(value, dict):
            raise InvalidPlannerOutput("Planner response must be a JSON object")
        cover = value.get("cover_letter")
        alignment, answers, next_steps = value.get("resume_alignment"), value.get("answers"), value.get("next_steps")
        if not isinstance(cover, str) or len(cover) > 30000:
            raise InvalidPlannerOutput("Planner response has an invalid cover letter")
        if not isinstance(alignment, list) or len(alignment) > 30 or not all(isinstance(item, str) and len(item) <= 1000 for item in alignment):
            raise InvalidPlannerOutput("Planner response has invalid resume alignment notes")
        if not isinstance(answers, dict) or len(answers) > 30 or not all(isinstance(k, str) and isinstance(v, str) and len(k) <= 200 and len(v) <= 4000 for k, v in answers.items()):
            raise InvalidPlannerOutput("Planner response has invalid answers")
        if not isinstance(next_steps, list) or len(next_steps) > 30 or not all(isinstance(item, str) and len(item) <= 1000 for item in next_steps):
            raise InvalidPlannerOutput("Planner response has invalid next steps")
        return cls(cover, alignment, answers, next_steps)
