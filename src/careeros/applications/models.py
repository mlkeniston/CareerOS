"""Bounded draft contracts and conservative, deterministic candidate evidence checks."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


class InvalidPlannerOutput(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    id: str
    category: Literal['resume', 'profile', 'approved_project', 'job']
    text: str
    attested: bool = False


@dataclass(slots=True)
class ClaimEvidence:
    claim_id: str
    text: str
    evidence_ids: list[str]
    quote_anchors: list[str]


@dataclass(frozen=True, slots=True)
class ClaimIssue:
    claim_id: str
    reason: str


@dataclass(slots=True)
class ApplicationDraft:
    resume_text: str
    cover_letter: str
    answers: dict[str, str]
    claims: list[ClaimEvidence]
    next_steps: list[str]

    @classmethod
    def parse(cls, value: object) -> 'ApplicationDraft':
        if not isinstance(value, dict):
            raise InvalidPlannerOutput('Planner response must be a JSON object')
        resume, cover = value.get('resume_text'), value.get('cover_letter')
        if not _text(resume, 30000) or not resume.strip():
            raise InvalidPlannerOutput('Planner response has invalid resume text')
        if not _text(cover, 30000):
            raise InvalidPlannerOutput('Planner response has an invalid cover letter')
        answers, steps, claims = value.get('answers'), value.get('next_steps'), value.get('claims')
        if not isinstance(answers, dict) or len(answers) > 30 or not all(_text(k, 200) and _text(v, 4000) for k, v in answers.items()):
            raise InvalidPlannerOutput('Planner response has invalid answers')
        if not _strings(steps, 30, 1000):
            raise InvalidPlannerOutput('Planner response has invalid next steps')
        if not isinstance(claims, list) or len(claims) > 100:
            raise InvalidPlannerOutput('Planner response has invalid claims')
        parsed, ids = [], set()
        for item in claims:
            if (not isinstance(item, dict) or not _text(item.get('claim_id'), 100)
                    or not item['claim_id'].strip() or item['claim_id'] in ids
                    or not _text(item.get('text'), 1000) or not item['text'].strip()
                    or not _strings(item.get('evidence_ids'), 5, 200, nonempty=True)
                    or not _strings(item.get('quote_anchors'), 5, 1000, nonempty=True)):
                raise InvalidPlannerOutput('Planner response has an invalid claim record')
            ids.add(item['claim_id'])
            parsed.append(ClaimEvidence(item['claim_id'], item['text'], item['evidence_ids'], item['quote_anchors']))
        return cls(resume, cover, answers, parsed, steps)


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and '\0' not in value


def _strings(value: object, limit: int, item_limit: int, nonempty: bool = False) -> bool:
    return (isinstance(value, list) and len(value) <= limit
            and all(_text(item, item_limit) and (not nonempty or item.strip()) for item in value))


def normalize_quote(value: str) -> str:
    """Normalize case, Unicode and whitespace; preserve numbers and punctuation."""
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _complete_quotes(text: str) -> set[str]:
    normalized = normalize_quote(text)
    # A quote must keep the complete statement, including negations and
    # qualifiers. Arbitrary substrings can reverse facts or split skill names.
    units = {normalized}
    for sentence in re.split(r'(?<=[.!?;])\s+', normalized):
        units.add(sentence)
        units.add(sentence.rstrip('.!?;'))
    return units


def _supported_wording(claim: str, quote: str) -> bool:
    if claim == quote:
        return True
    # A resume's implied first person may be made explicit for a letter. The
    # entire action and every qualifier stay intact; no free semantic rewrite.
    actions = r'built|developed|implemented|designed|led|managed|created|used|wrote|improved|tested|maintained|delivered'
    return claim == 'i ' + quote and bool(re.match(r'(?:' + actions + r')\b', quote))


def _material_statements(value: str) -> list[str]:
    # Split before whitespace normalization so explicit output lines remain
    # separate statements. Decimal punctuation without whitespace is a token.
    return [normalized for part in re.split(r'\n+|(?<=[.!?;])\s+', unicodedata.normalize('NFKC', value))
            if (normalized := normalize_quote(part).rstrip('.!?;')) and re.search(r'\w', normalized)]


def _contains_statements(output: list[str], claim: list[str]) -> bool:
    return bool(claim) and any(output[index:index + len(claim)] == claim
                               for index in range(len(output) - len(claim) + 1))


def _numbers(value: str) -> set[str]:
    return set(re.findall(r'(?<!\w)\d+(?:[.,]\d+)*(?:%|\+)?(?!\w)', value))


def validate_claims(draft: ApplicationDraft, evidence_snapshot: dict[str, EvidenceItem]) -> list[ClaimIssue]:
    # Direct dataclass construction and manual edits have the same bounds as JSON.
    from dataclasses import asdict
    try:
        ApplicationDraft.parse(asdict(draft))
    except (InvalidPlannerOutput, TypeError) as exc:
        return [ClaimIssue('draft', str(exc))]
    issues = []
    materials = [('resume_text', draft.resume_text), ('cover_letter', draft.cover_letter), *draft.answers.items()]
    output_statements = [_material_statements(value) for _, value in materials]
    supported_statements = set()
    supported_numbers = set()
    for claim in draft.claims:
        issue_count = len(issues)
        sources = []
        invalid = False
        for evidence_id in claim.evidence_ids:
            item = evidence_snapshot.get(evidence_id)
            if item is None:
                issues.append(ClaimIssue(claim.claim_id, f'Unknown evidence ID: {evidence_id}'))
                invalid = True
            elif item.category not in {'resume', 'profile', 'approved_project'}:
                issues.append(ClaimIssue(claim.claim_id, 'Claim must reference candidate evidence, never employer text'))
                invalid = True
            elif item.category == 'profile' and not item.attested:
                issues.append(ClaimIssue(claim.claim_id, 'Profile fact requires user attestation'))
                invalid = True
            else:
                sources.append(item)
        if invalid:
            continue
        source_texts = [normalize_quote(item.text) for item in sources]
        complete_quotes = set().union(*(_complete_quotes(item.text) for item in sources))
        anchors = [normalize_quote(anchor) for anchor in claim.quote_anchors]
        if not sources:
            issues.append(ClaimIssue(claim.claim_id, 'Claim requires candidate evidence'))
            continue
        if not anchors and not any(item.category == 'profile' and item.attested for item in sources):
            issues.append(ClaimIssue(claim.claim_id, 'Claim requires an exact normalized quote anchor'))
        elif any(anchor not in complete_quotes for anchor in anchors):
            issues.append(ClaimIssue(claim.claim_id, 'Quote anchor must match a complete statement in linked candidate evidence'))
        numbers = _numbers(normalize_quote(claim.text))
        candidate_numbers = _numbers(' '.join(source_texts))
        if not numbers <= candidate_numbers:
            issues.append(ClaimIssue(claim.claim_id, 'Unsupported numeric claim in candidate evidence'))
        # Exact source wording is deliberately required: an anchor alone cannot
        # prove an arbitrary paraphrase or authorize extra skills/credentials.
        normalized = normalize_quote(claim.text)
        supporting = anchors or [normalize_quote(item.text) for item in sources if item.attested and item.category == 'profile']
        if not any(_supported_wording(normalized, quote) for quote in supporting):
            issues.append(ClaimIssue(claim.claim_id, 'Claim text is not supported by its candidate quote anchors'))
        statements = _material_statements(claim.text)
        if not any(_contains_statements(output, statements) for output in output_statements):
            issues.append(ClaimIssue(claim.claim_id, 'Claim text is absent as complete statements from application materials'))
        if len(issues) == issue_count:
            supported_statements.update(statements)
            supported_numbers.update(numbers)
    # Check whole output statements, never delete substrings from a mutable
    # remainder. Two supported claims cannot join into a different fact/token.
    for (label, value), statements in zip(materials, output_statements):
        if any(statement not in supported_statements for statement in statements):
            issues.append(ClaimIssue(label, 'Application material contains untraced text; link every complete statement to candidate evidence'))
        if not _numbers(normalize_quote(value)) <= supported_numbers:
            issues.append(ClaimIssue(label, 'Application material contains unsupported numeric output'))
    return issues
