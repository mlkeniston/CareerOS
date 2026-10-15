"""Deterministic preparation gates; eligibility is supplied only by the user."""
from __future__ import annotations

import re
from dataclasses import dataclass

from careeros.jobs.location import classify_location, US


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    reason: str


def _normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9+#]+', ' ', value.casefold()).strip()


def _role_terms(value: str) -> set[str]:
    canonical = {'engineering': 'engineer', 'engineers': 'engineer'}
    return {canonical.get(term, term) for term in _normalize(value).split()}


def role_overlap(title: str, role: str) -> int:
    title_terms = _role_terms(title)
    role_terms = _role_terms(role) - {'intern', 'internship', 'internships', 'junior', 'entry', 'level', 'graduate', 'new'}
    return len(role_terms) if role_terms and role_terms <= title_terms else 0


def matches_preferred_location(job, preferences: list[str]) -> bool:
    preferences = [_normalize(value) for value in preferences if value.strip()]
    if not preferences:
        return True
    if any(preference in {'united states', 'united states of america', 'usa', 'u s a', 'nationwide', 'anywhere in the us'} for preference in preferences):
        return classify_location(job.location) == US
    location = _normalize(job.location)
    remote = job.remote or 'remote' in location.split()
    return any(remote if 'remote' in preference.split() else f' {preference} ' in f' {location} ' for preference in preferences)


_MONTHS = {name: i for i, name in enumerate(('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'), 1)}


def _dates(text):
    values = [(int(y), int(m)) for y, m in re.findall(r'\b(20\d{2})-(0[1-9]|1[0-2])\b', text)]
    for month, year in re.findall(r'\b(' + '|'.join(_MONTHS) + r')\s+(20\d{2})\b', text.casefold()):
        values.append((int(year), _MONTHS[month]))
    return values


_COUNTRY_CODES = {
    'united states': 'US', 'usa': 'US', 'us': 'US', 'u s': 'US', 'american': 'US',
    'canada': 'CA', 'canadian': 'CA',
    'united kingdom': 'UK', 'uk': 'UK', 'u k': 'UK', 'british': 'UK',
}
_COUNTRY_PATTERN = '|'.join(_COUNTRY_CODES)


def _country(text):
    # This accepts a country token already extracted from its eligibility clause.
    # Searching arbitrary prose for 'us' mistakes a pronoun for a country.
    return _COUNTRY_CODES.get(_normalize(text))


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
        match = re.fullmatch(r"(?:authorized to work in )?(" + _COUNTRY_PATTERN + r")(?: citizen| citizenship| work authorization)?", normalized)
        if not match:
            return None
        countries.append(_country(match[1]))
    return country in countries


def _condition_result(condition: str, facts: dict[str, str]) -> bool | None:
    # An exact employer condition may be explicitly answered in Other facts.
    direct = facts.get(condition.casefold())
    if direct in {'yes', 'true', 'met'}:
        return True
    if direct in {'no', 'false', 'not met'}:
        return False
    c = ' '.join(condition.casefold().split())
    if re.search(r'currently pursuing .{0,180}\b(?:bachelor|master|degree)', c):
        value = facts.get('enrollment')
        return value == 'yes' if value in {'yes', 'no'} else None
    families = [r'sponsor', r'citizen', r'us person', r'authori[sz]|right to work|eligible to work',
                r'enroll', r'graduat', r'experience', r'clearance']
    if sum(bool(re.search(pattern, c)) for pattern in families) > 1:
        return None
    if 'us person' in c:
        value = facts.get('us_person')
        return value == 'yes' if value in {'yes', 'no'} else None
    if (' and ' in c or ' or ' in c) and not (('between' in c and 'graduat' in c) or 'enroll' in c):
        return None
    if 'sponsor' in c:
        if not re.fullmatch(r'(?:we (?:cannot|do not|are unable to) (?:provide|offer) (?:visa )?sponsorship|no (?:visa )?sponsorship(?: available| provided| offered)?)', c):
            return None
        value = facts.get('sponsorship')
        return value in {'no', 'not needed', 'none'} if value in {'yes', 'no', 'not needed', 'none', 'needed'} else None
    if 'citizen' in c:
        match = re.fullmatch(r'(?:must be|applicants must be|candidates must be) (?:a )?(' + _COUNTRY_PATTERN + r') citizen', c)
        if match:
            return _country_fact_matches(facts.get('citizenship'), _country(match[1]))
        if 'itar' in c and re.search(r'\bus citizen(?:ship)?\b', c):
            person = facts.get('us_person')
            if person in {'yes', 'no'}:
                return person == 'yes'
            return _country_fact_matches(facts.get('citizenship'), US.upper())
        return None
    if re.search(r'authori[sz]|right to work|eligible to work', c):
        match = re.fullmatch(r'(?:must be|applicants must be|candidates must be) (?:authorized|authorised|eligible) to work in (?:the )?(' + _COUNTRY_PATTERN + r')(?: to join us)?', c)
        return _country_fact_matches(facts.get('work_authorization'), _country(match[1])) if match else None
    if 'enroll' in c:
        if not re.fullmatch(r'(?:(?:must be|applicants must be|candidates must be) )?(?:currently )?enrolled(?: in .{0,240}\bdegree program(?: in .{1,160})?)?', c):
            return None
        value = facts.get('enrollment')
        return value == 'yes' if value in {'yes', 'no'} else None
    if re.search(r'graduat', c):
        date_pattern = r'(?:20\d{2}-(?:0[1-9]|1[0-2])|(?:' + '|'.join(_MONTHS) + r') 20\d{2})'
        if not re.fullmatch(r'must graduate between ' + date_pattern + ' and ' + date_pattern, c):
            return None
        dates = _dates(c)
        user_dates = _dates(facts.get('graduation', ''))
        return min(dates) <= user_dates[0] <= max(dates) if len(dates) == 2 and len(user_dates) == 1 else None
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
    # Keep U.S. abbreviations intact so their periods do not manufacture
    # fragments such as "citizen, U" and "lawful permanent resident".
    text = re.sub(r'(?i)\bU\s*\.\s*S\s*\.', 'US', text)
    # Sentence/line boundaries prevent one known fact covering another condition.
    for condition in re.split(r'[.!?;\n]+\s*', text):
        condition = condition.strip()
        if not condition:
            continue
        material = re.search(r'(?i)\b(citizen\w*|authori[sz]\w*|enroll\w*|graduat\w*|sponsor\w*|security clearance|right to work|eligible to work|degree|bachelor\w*|master\w*|phd|experience|work permit|visa|residen\w*|years old|us persons?|persons only)\b', condition)
        years = re.search(r'(?i)\b\d+\+?\s+years?\b.*\bexperience\b', condition)
        # Headings and descriptive/EEO prose are not candidate conditions.
        if re.search(r'(?i)\b(equal opportunity|all applicants will be considered|legally protected characteristic)\b', condition):
            continue
        if re.search(r'(?i)\bUS person.{0,80}\baccording to .{0,80}\bdefinition\b', condition):
            continue
        if re.search(r'(?i)\b(?:some|certain) positions (?:will|may) require\b', condition):
            continue
        if re.search(r'(?i)\bprogram intended .{0,160}\bcurrently enrolled\b.{0,80}\brecent graduates\b', condition):
            continue
        if re.search(r'(?i)\b(?:gain|gaining|develop)\s+(?:[a-z]+\s+){0,3}experience\b', condition):
            continue
        experience = re.search(r'(?i)\bexperience\b', condition)
        other_material = re.search(r'(?i)\b(citizen\w*|authori[sz]\w*|enroll\w*|graduat\w*|sponsor\w*|security clearance|right to work|eligible to work|degree|bachelor\w*|master\w*|phd|work permit|visa|residen\w*|years old|us persons?|persons only)\b', condition)
        word_years = re.search(r'(?i)\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\+?\s+years?\b', condition)
        if experience and not other_material and not years and not word_years:
            continue
        if not (material or years):
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
    country_status = classify_location(job.location)
    country_passed = country_status == US
    country_reason = (
        "Location is confirmed in the United States" if country_passed else
        "Location is outside the United States" if country_status == "outside_us" else
        "Location is unclear; confirm a U.S. state or country before preparation"
    )
    return [
        GateResult('verified', verification.status == 'verified', verification.reason),
        GateResult('country', country_passed, country_reason),
        GateResult('role', role, 'Matches a saved target role' if role else 'Role does not overlap a saved target role'),
        GateResult('location', location, 'Matches saved location or remote preference' if location else 'Outside saved location preferences'),
        GateResult('details', details, 'Employer text is sufficient to prepare' if details else 'Employer text is too sparse to prepare'),
        _eligibility(verification.text, profile.eligibility_facts),
    ]
