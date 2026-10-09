from __future__ import annotations

import re

from careeros.jobs.models import JobListing


_TAXONOMY = (
    ("software", ("software", "developer", "backend", "frontend", "full stack", "web developer", "mobile app", "programmer", "python", "javascript", "typescript", "fastapi", "react")),
    ("data", ("data scientist", "data analyst", "data engineer", "analytics", "business intelligence", "sql", "tableau", "power bi")),
    ("AI", ("machine learning", "artificial intelligence", "ai engineer", "llm", "genai", "natural language processing", "computer vision")),
    ("security", ("cybersecurity", "security analyst", "information security", "soc analyst", "penetration testing", "infosec")),
    ("product", ("product manager", "product owner", "product analyst", "product operations")),
    ("QA", ("quality assurance", "qa engineer", "test automation", "software tester", "sdet")),
    ("design", ("ux designer", "ui designer", "product designer", "user experience", "user interface", "ux researcher")),
    ("IT", ("it support", "help desk", "systems administrator", "technical support")),
    ("cloud", ("cloud engineer", "cloud architect", "aws", "azure", "gcp", "cloud platform")),
    ("infrastructure", ("devops", "site reliability", "infrastructure", "platform engineer", "network engineer", "kubernetes", "sre")),
)
_EARLY_CAREER = ("intern", "internship", "junior", "entry level", "new grad", "graduate", "early career", "co op", "apprentice", "engineer i", "level 1")
_SENIOR = ("senior", "sr ", "staff", "principal", "lead", "director", "head of", "vice president")


def score_technology_role(job: JobListing) -> tuple[int, list[str]]:
    """Score a listing with a small keyword taxonomy; never invokes a model."""
    title = _normalize(job.title)
    description = _normalize(job.description)
    kind = _normalize(" ".join((job.kind, job.original_kind)))
    matched = []
    title_categories = set()
    description_categories = set()
    for category, terms in _TAXONOMY:
        normalized_terms = tuple(_normalize(term) for term in terms)
        if _contains_any(title, normalized_terms):
            title_categories.add(category)
        if _contains_any(description, normalized_terms):
            description_categories.add(category)
        if category in title_categories or category in description_categories:
            matched.append(category)

    if not matched:
        return 0, []

    score = (45 if title_categories else 0) + (20 if description_categories else 0)
    reasons = [f"Technology role: {category}" for category in matched]
    early = _contains_any(_normalize(f"{title} {kind}"), _EARLY_CAREER)
    if early:
        score += 35
        reasons.append("Internship or early-career signal")
    if _contains_any(title, _SENIOR):
        score -= 40
        reasons.append("Senior-level title lowers match")
    return max(0, min(100, score)), reasons


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", value.casefold()).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)
