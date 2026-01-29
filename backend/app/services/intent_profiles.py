from __future__ import annotations

"""Domain intent profiles loaded from the plumbing intent mapping CSV.

This module exposes a lightweight, cached view over the structured
"Intent Mapping - Sheet1.csv" document so that:

- intent detection can map utterances to a specific workflow/issue type
- the LLM system prompt can be specialised per-issue
- downstream workflows can see richer intent metadata (purpose, routing
  logic, clarifying questions, etc.).

It is intentionally simple and fast: CSV is parsed once and cached in
memory; matching is rule-based and cheap compared to an LLM call.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple
import csv
import re


INTENT_CSV_RELATIVE_PATH = Path("docs") / "Intent Mapping - Sheet1.csv"


@dataclass
class IssueIntentProfile:
    """Structured view of a single row in the intent mapping sheet."""

    id: str  # stable slug, e.g. "emergency_plumbing"
    workflow: str
    purpose: str
    customer_intent: str
    training_utterances: List[str]
    common_phrases: List[str]
    jobs_covered: List[str]
    clarifying_questions: List[str]
    routing_logic: str
    automation_actions: str


def _project_root() -> Path:
    # backend/app/services/intent_profiles.py -> project root is 3 parents up
    return Path(__file__).resolve().parents[3]


def _slugify(text: str) -> str:
    text = text.strip().lower()
    # Replace non-alphanumeric with underscores, collapse repeats
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def _split_semicolon_field(raw: str) -> List[str]:
    if not raw:
        return []
    # The sheet uses semicolons between example phrases; quotes are optional
    parts = [p.strip().strip("\"'") for p in raw.split(";")]
    # Remove empties and normalise whitespace
    return [re.sub(r"\s+", " ", p) for p in parts if p]


@lru_cache(maxsize=1)
def _load_profiles_from_csv() -> List[IssueIntentProfile]:
    csv_path = _project_root() / INTENT_CSV_RELATIVE_PATH
    if not csv_path.exists():
        # Fail soft: return empty list so callers can handle absence.
        print(f"⚠️ Intent mapping CSV not found at {csv_path}")
        return []

    profiles: List[IssueIntentProfile] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            workflow = (row.get("Workflow") or "").strip()
            if not workflow:
                # Skip incomplete rows
                continue

            profile_id = _slugify(workflow)

            training_utts = _split_semicolon_field(row.get("Training Utterances", ""))
            common_phrases = _split_semicolon_field(row.get("Common Phrases", ""))
            jobs_covered = _split_semicolon_field(row.get("Jobs Covered", ""))
            clarifying_questions = _split_semicolon_field(row.get("Clarifying Questions", ""))

            profiles.append(
                IssueIntentProfile(
                    id=profile_id,
                    workflow=workflow,
                    purpose=(row.get("Purpose") or "").strip(),
                    customer_intent=(row.get("Customer Intent") or "").strip(),
                    training_utterances=training_utts,
                    common_phrases=common_phrases,
                    jobs_covered=jobs_covered,
                    clarifying_questions=clarifying_questions,
                    routing_logic=(row.get("Routing Logic") or "").strip(),
                    automation_actions=(row.get("Automation Actions") or "").strip(),
                )
            )

    return profiles


def get_issue_profiles() -> List[IssueIntentProfile]:
    """Return all known issue intent profiles from the CSV (cached)."""

    return list(_load_profiles_from_csv())


def get_issue_profile(issue_id: str) -> Optional[IssueIntentProfile]:
    """Look up a single profile by its stable slug id."""

    slug = _slugify(issue_id)
    for p in _load_profiles_from_csv():
        if p.id == slug:
            return p
    return None


def match_issue_intent(user_text: str) -> Tuple[Optional[IssueIntentProfile], float]:
    """Best-effort matching of free text to a configured issue intent.

    This is intentionally simple: it uses phrase containment and a small
    heuristic scoring model over the "Training Utterances" and
    "Common Phrases" columns. It is *not* a classifier; just a cheap
    hint to supplement the high-level intent.

    Returns (profile, score) where score is in [0, 1].
    """

    text = (user_text or "").lower()
    if not text:
        return None, 0.0

    best_profile: Optional[IssueIntentProfile] = None
    best_raw_score = 0.0

    for profile in _load_profiles_from_csv():
        score = 0.0

        # Direct phrase hits from training utterances & common phrases
        for phrase in profile.training_utterances + profile.common_phrases:
            p = phrase.strip().lower()
            if not p or len(p) < 4:
                continue
            if p in text:
                # Weight exact phrase matches quite strongly
                score += 3.0

        # Small bonus if key words from workflow name appear
        wf_tokens = [t for t in re.split(r"\W+", profile.workflow.lower()) if t]
        for tok in wf_tokens:
            if tok and tok in text:
                score += 1.0

        if score > best_raw_score:
            best_raw_score = score
            best_profile = profile

    if not best_profile or best_raw_score <= 0:
        return None, 0.0

    # Squash into [0, 1] with a simple heuristic: assume 10+ is "very sure".
    confidence = max(0.1, min(1.0, best_raw_score / 10.0))
    return best_profile, confidence
