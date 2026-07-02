"""Cross-source player identity resolution.

None of FBref, Understat, Transfermarkt, or API-Football share a common player ID.
This module maps each source's native (source, source_player_id) pair onto our
canonical `player_id`, in priority order:

  1. Manual override (player_alias_override) always wins.
  2. Exact match: normalized name + exact date_of_birth -> confidence 1.0, auto-accept.
  3. Fuzzy match: normalized-name similarity + team-hint agreement -> weighted confidence.
     >=0.90 auto-accept, 0.75-0.90 goes to the review queue, <0.75 becomes a new player
     (and is still logged to the queue, to catch missed matches later).
"""
import sqlite3
from datetime import date
from typing import Optional

from rapidfuzz import fuzz
from unidecode import unidecode

AUTO_ACCEPT_THRESHOLD = 0.90
REVIEW_QUEUE_THRESHOLD = 0.75


def normalize_name(name: str) -> str:
    name = unidecode(name or "").lower().strip()
    for suffix in (" jr.", " jr", " sr.", " sr"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return " ".join(name.split())


def _name_score(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize_name(a), normalize_name(b)) / 100.0


def _team_score(hint_a: Optional[str], hint_b: Optional[str]) -> float:
    if not hint_a or not hint_b:
        return 0.0
    # token_set_ratio (not token_sort_ratio) so "Arsenal" vs "Arsenal Football Club" still
    # matches -- sources vary widely in how verbose their club names are.
    return 1.0 if fuzz.token_set_ratio(normalize_name(hint_a), normalize_name(hint_b)) >= 85 else 0.0


def resolve_player_id(
    conn: sqlite3.Connection,
    source: str,
    source_player_id: str,
    source_name: str,
    date_of_birth: Optional[str] = None,
    team_hint: Optional[str] = None,
) -> Optional[int]:
    """Return our canonical player_id for this source record, or None if it was
    routed to the review queue instead of being auto-resolved."""

    # 1. Manual override always wins.
    override = conn.execute(
        "SELECT player_id FROM player_alias_override WHERE source = ? AND source_player_id = ?",
        (source, source_player_id),
    ).fetchone()
    if override is not None:
        if override["player_id"] is None:
            _enqueue_review(conn, source, source_player_id, source_name, date_of_birth, team_hint, None, None)
            return None
        _ensure_source_ref(conn, override["player_id"], source, source_player_id, source_name, 1.0, "manual_override")
        return override["player_id"]

    # Already resolved in a prior run?
    existing = conn.execute(
        "SELECT player_id FROM player_source_ref WHERE source = ? AND source_player_id = ?",
        (source, source_player_id),
    ).fetchone()
    if existing is not None:
        _touch_team_hint(conn, existing["player_id"], team_hint)
        return existing["player_id"]

    candidates = conn.execute("SELECT player_id, canonical_name, date_of_birth, last_team_hint FROM player").fetchall()

    # 2. Exact match: normalized name + DOB.
    if date_of_birth:
        for cand in candidates:
            if cand["date_of_birth"] == date_of_birth and normalize_name(cand["canonical_name"]) == normalize_name(source_name):
                _ensure_source_ref(conn, cand["player_id"], source, source_player_id, source_name, 1.0, "exact_dob_name")
                _touch_team_hint(conn, cand["player_id"], team_hint)
                return cand["player_id"]

    # 3. Fuzzy match: name + team.
    best_score, best_candidate = 0.0, None
    for cand in candidates:
        name_sim = _name_score(source_name, cand["canonical_name"])
        if name_sim < 0.80:  # cheap prefilter before weighting
            continue
        team_sim = _team_score(team_hint, cand["last_team_hint"])
        score = 0.7 * name_sim + 0.3 * team_sim
        # A near-exact name match should never be silently treated as "no match" just because
        # the team hint differs (e.g. a mid-season transfer, or a source-specific team-name
        # quirk our normalization didn't catch) -- floor it at the review-queue threshold so a
        # human sees it instead of it becoming an untracked duplicate player.
        if name_sim >= 0.93:
            score = max(score, REVIEW_QUEUE_THRESHOLD)
        if score > best_score:
            best_score, best_candidate = score, cand

    if best_candidate is not None and best_score >= AUTO_ACCEPT_THRESHOLD:
        _ensure_source_ref(conn, best_candidate["player_id"], source, source_player_id, source_name, best_score, "fuzzy_name_team")
        _touch_team_hint(conn, best_candidate["player_id"], team_hint)
        return best_candidate["player_id"]

    if best_candidate is not None and best_score >= REVIEW_QUEUE_THRESHOLD:
        _enqueue_review(conn, source, source_player_id, source_name, date_of_birth, team_hint, best_candidate["player_id"], best_score)
        return None

    # No good candidate: create a new player, but still log to the queue (low priority)
    # so a human can catch missed matches later.
    cur = conn.execute(
        "INSERT INTO player (canonical_name, date_of_birth, last_team_hint) VALUES (?, ?, ?)",
        (source_name, date_of_birth, team_hint),
    )
    new_player_id = cur.lastrowid
    _ensure_source_ref(conn, new_player_id, source, source_player_id, source_name, 1.0, "seed")
    _enqueue_review(conn, source, source_player_id, source_name, date_of_birth, team_hint, new_player_id, best_score, status="created_new")
    conn.commit()
    return new_player_id


def _ensure_source_ref(conn, player_id: int, source: str, source_player_id: str, source_name: str, confidence: float, method: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO player_source_ref
           (player_id, source, source_player_id, source_name, match_confidence, match_method)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (player_id, source, source_player_id, source_name, confidence, method),
    )


def _touch_team_hint(conn, player_id: int, team_hint: Optional[str]) -> None:
    if team_hint:
        conn.execute("UPDATE player SET last_team_hint = ? WHERE player_id = ?", (team_hint, player_id))


def _enqueue_review(conn, source, source_player_id, source_name, date_of_birth, team_hint, candidate_player_id, candidate_score, status="pending") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO player_match_review_queue
           (source, source_player_id, source_name, source_dob, source_team_hint, candidate_player_id, candidate_score, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (source, source_player_id, source_name, date_of_birth, team_hint, candidate_player_id, candidate_score, status),
    )
