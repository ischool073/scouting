PRAGMA foreign_keys = ON;

-- ============ Reference / dimension tables ============

CREATE TABLE IF NOT EXISTS competition (
    competition_id TEXT PRIMARY KEY,   -- matches config/leagues.yaml `id`, e.g. 'ENG1'
    country TEXT NOT NULL,
    tier INTEGER NOT NULL,             -- 1, 2, or 3
    display_name TEXT NOT NULL,
    fbref_source TEXT,                 -- 'soccerdata' | 'fbrefdata' | NULL
    fbref_key TEXT,
    understat_key TEXT,
    transfermarkt_comp_id TEXT
);

CREATE TABLE IF NOT EXISTS season (
    season_id TEXT PRIMARY KEY,        -- e.g. '2024-2025'
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS team (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    country TEXT
);

CREATE TABLE IF NOT EXISTS team_source_ref (
    team_id INTEGER NOT NULL REFERENCES team(team_id),
    source TEXT NOT NULL,              -- 'fbref' | 'understat' | 'transfermarkt' | 'api_football'
    source_team_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    PRIMARY KEY (source, source_team_id)
);

CREATE TABLE IF NOT EXISTS team_competition_season (
    team_id INTEGER NOT NULL REFERENCES team(team_id),
    competition_id TEXT NOT NULL REFERENCES competition(competition_id),
    season_id TEXT NOT NULL REFERENCES season(season_id),
    PRIMARY KEY (team_id, competition_id, season_id)
);

-- ============ Player identity core ============

CREATE TABLE IF NOT EXISTS player (
    player_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    date_of_birth DATE,
    nationality TEXT,
    primary_position TEXT,
    last_team_hint TEXT,                -- most recently seen team name (raw string, any source); cheap disambiguation signal
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS player_source_ref (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES player(player_id),
    source TEXT NOT NULL,
    source_player_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    match_confidence REAL NOT NULL,
    match_method TEXT NOT NULL,        -- 'exact_dob_name' | 'fuzzy_name_team' | 'manual_override' | 'seed'
    resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_by TEXT,
    UNIQUE (source, source_player_id)
);

CREATE INDEX IF NOT EXISTS idx_player_source_ref_player ON player_source_ref(player_id);

CREATE TABLE IF NOT EXISTS player_match_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_player_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_dob DATE,
    source_team_hint TEXT,
    candidate_player_id INTEGER REFERENCES player(player_id),
    candidate_score REAL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'rejected' | 'created_new'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    UNIQUE (source, source_player_id)
);

CREATE TABLE IF NOT EXISTS player_alias_override (
    source TEXT NOT NULL,
    source_player_id TEXT NOT NULL,
    player_id INTEGER REFERENCES player(player_id),   -- NULL = force to review queue, never auto-match
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source, source_player_id)
);

-- ============ Per-source stats snapshots (append-only) ============

CREATE TABLE IF NOT EXISTS stats_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES player(player_id),
    source TEXT NOT NULL,
    competition_id TEXT REFERENCES competition(competition_id),
    season_id TEXT REFERENCES season(season_id),
    team_id INTEGER REFERENCES team(team_id),
    stat_type TEXT NOT NULL,           -- 'standard' | 'shooting' | 'passing' | 'defense' | 'market_value' | 'spotcheck' | ...
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stats_snapshot_lookup ON stats_snapshot(player_id, source, season_id);

-- Query-friendly derived numeric columns actually used by report generation.
CREATE TABLE IF NOT EXISTS player_season_stat_flat (
    player_id INTEGER NOT NULL REFERENCES player(player_id),
    season_id TEXT NOT NULL REFERENCES season(season_id),
    competition_id TEXT NOT NULL REFERENCES competition(competition_id),
    minutes INTEGER,
    goals INTEGER,
    assists INTEGER,
    xg REAL,
    xa REAL,
    npxg REAL,
    progressive_carries INTEGER,
    progressive_passes INTEGER,
    tackles_won INTEGER,
    market_value_eur INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (player_id, season_id, competition_id)
);

-- ============ Ingestion run bookkeeping ============

CREATE TABLE IF NOT EXISTS ingest_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    competition_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,              -- 'running' | 'success' | 'failed'
    rows_written INTEGER,
    error_message TEXT
);
