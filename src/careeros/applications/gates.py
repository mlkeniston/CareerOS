"""Deterministic preparation gates; eligibility is supplied only by the user."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    reason: str


def _normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9+#]+', ' ', value.casefold()).strip()


def role_overlap(title: str, role: str) -> int:
    title_terms = set(_normalize(title).split())
    role_terms = set(_normalize(role).split()) - {'intern', 'internship', 'junior', 'entry', 'level', 'graduate', 'new'}
    return len(role_terms) if role_terms and role_terms <= title_terms else 0


def matches_preferred_location(job, preferences: list[str]) -> bool:
    preferences = [_normalize(value) for value in preferences if value.strip()]
    if not preferences:
        return True
    location = _normalize(job.location)
    remote = job.remote or 'remote' in location.split()
    return any(remote if 'remote' in preference.split() else f' {preference} ' in f' {location} ' for preference in preferences)


_MONTHS = {name: i for i, name in enumerate(('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'), 1)}


def _dates(text):
    values = [(int(y), int(m)) for y, m in re.findall(r'\b(20\d{2})-(0[1-9]|1[0-2])\b', text)]
    for month, year in re.findall(r'\b(' + '|'.join(_MONTHS) + r')\s+(20\d{2})\b', text.casefold()):
        values.append((int(year), _MONTHS[month]))
    return values


def _country(text):
    text = _normalize(text)
    if re.search(r'\b(united states|usa|us|u s|american)\b', text):
        return 'US'
    if re.search(r'\b(canada|canadian)\b', text):
        return 'CA'
    if re.search(r'\b(united kingdom|uk|u k|british)\b', text):
        return 'UK'
    return None


def _country_fact_matches(value: str | None, country: str | None) -> bool | None:
    if not value or not country:
        return None
    if re.search(r"\b(maybe|pending|unknown|unsure|uncertain|not sure)\b", value):
        return None
    if re.search(r"\b(no|not|unauthorized|ineligible|cannot)\b", value):
        return False
    countries = []
    for item in re.split(r"[,;/]", value):
        normalized = _normalize(item)
        # A country mention inside arbitrary prose is not an affirmative fact.
        if not re.fullmatch(r"(?:authorized to work in )?(?:united states|usa|us|u s|american|canada|canadian|united kingdom|uk|u k|british)(?: citizen| citizenship| work authorization)?", normalized):
            return None
        countries.append(_country(item))
    return country in countries


def _condition_result(condition: str, facts: dict[str, str]) -> bool | None:
    # An exact employer condition may be explicitly answered in Other facts.
    direct = facts.get(condition.casefold())
    if direct in {'yes', 'true', 'met'}:
        return True
    if direct in {'no', 'false', 'not met'}:
        return False
    c = condition.casefold()
    families = [r'sponsor', r'citizen', r'authori[sz]|right to work|eligible to work',
                r'enroll', r'graduat', r'experience', r'clearance']
    if sum(bool(re.search(pattern, c)) for pattern in families) > 1:
        return None
    if (' and ' in c or ' or ' in c) and not ('between' in c and 'graduat' in c):
        return None
    if 'sponsor' in c:
        value = facts.get('sponsorship')
        if value is None:
            return None
        if re.search(r'no|not|cannot|unable|without', c):
            return value in {'no', 'not needed', 'none'} if value in {'yes', 'no', 'not needed', 'none', 'needed'} else None
        return None
    if 'citizen' in c:
        value = facts.get('citizenship')
        country = _country(c)
        return _country_fact_matches(value, country)
    if re.search(r'authori[sz]|right to work|eligible to work', c):
        value = facts.get('work_authorization')
        country = _country(c)
        return _country_fact_matches(value, country)
    if 'enroll' in c:
        value = facts.get('enrollment')
        # More specific degree or study requirements need an exact user answer.
        if re.search(r'bachelor|master|phd|computer science|engineering', c):
            return None
        return value == 'yes' if value in {'yes', 'no'} else None
    if re.search(r'graduat', c):
        value = facts.get('graduation')
        dates = _dates(c)
        user_dates = _dates(value or '')
        if len(user_dates) != 1:
            return None
        if len(dates) == 2 and ('between' in c or 'through' in c):
            return min(dates) <= user_dates[0] <= max(dates)
        return None
    if 'experience' in c:
        value = facts.get('experience_years')
        required = re.search(r'\b(\d+)\+?\s+years?\b', c)
        # Domain-specific experience cannot be resolved from total years.
        if not required or not re.fullmatch(r'(?:requires?|minimum(?: of)?|at least|must have)\s+\d+\+?\s+years?\s+(?:of\s+)?experience', c):
            return None
        try:
            return float(value) >= int(required[1]) if value is not None and float(value) >= 0 else None
        except ValueError:
            return None
    return None


def _eligibility(text: str, facts: dict[str, str]) -> GateResult:
    facts = {key.casefold().strip(): value.casefold().strip() for key, value in facts.items()}
    failures = []
    # Sentence/line boundaries prevent one known fact covering another condition.
    for condition in re.split(r'[.!?;\n]+\s*', text):
        condition = condition.strip()
        if not condition:
            continue
        material = re.search(r'(?i)\b(citizen\w*|authori[sz]\w*|enroll\w*|graduat\w*|sponsor\w*|security clearance|right to work|eligible to work|degree|bachelor\w*|master\w*|phd|experience|work permit|visa|residen\w*|years old|persons only)\b', condition)
        years = re.search(r'(?i)\b\d+\+?\s+years?\b.*\bexperience\b', condition)
        other = re.search(r'(?i)\b(must|required|requires?|minimum|at least)\b', condition)
        if not (material or years or other):
            continue
        result = _condition_result(condition, facts)
        if result is None:
            failures.append(f'Unknown: {condition}')
        elif not result:
            failures.append(f'Not met: {condition}')
    return GateResult('eligibility', not failures, '; '.join(failures) if failures else 'No unresolved material eligibility conditions')


def evaluate_application_gates(job, profile, verification) -> list[GateResult]:
    roles = profile.target_roles or []
    location = matches_preferred_location(job, profile.preferred_locations or [])
    role = any(role_overlap(job.title, saved) for saved in roles)
    details = len(verification.text.strip()) >= 160 and len(verification.text.split()) >= 25
    return [
        GateResult('verified', verification.status == 'verified', verification.reason),
        GateResult('role', role, 'Matches a saved target role' if role else 'Role does not overlap a saved target role'),
        GateResult('location', location, 'Matches saved location or remote preference' if location else 'Outside saved location preferences'),
        GateResult('details', details, 'Employer text is sufficient to prepare' if details else 'Employer text is too sparse to prepare'),
        _eligibility(verification.text, profile.eligibility_facts),
    ]
