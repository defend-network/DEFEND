PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS matches (
  match_id TEXT PRIMARY KEY,
  date TEXT,
  event_name TEXT NOT NULL,
  best_of INTEGER NOT NULL,
  player_a_id TEXT,
  player_a_name TEXT NOT NULL,
  player_b_id TEXT,
  player_b_name TEXT NOT NULL,
  winner_id TEXT,
  games_a INTEGER,
  games_b INTEGER,
  source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS live_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  sets_a INTEGER NOT NULL,
  sets_b INTEGER NOT NULL,
  points_a INTEGER NOT NULL,
  points_b INTEGER NOT NULL,
  server TEXT,
  raw_json TEXT,
  FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bets (
  bet_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  match_id TEXT NOT NULL,
  book TEXT,
  market TEXT,
  selection TEXT,
  odds REAL NOT NULL,
  stake REAL NOT NULL,
  hard_pass INTEGER NOT NULL DEFAULT 0,
  soft_score REAL,
  model_adjust REAL,
  final_score REAL,
  decision TEXT,
  features_json TEXT,
  override INTEGER NOT NULL DEFAULT 0,
  override_reason TEXT,
  result TEXT,
  pnl REAL,
  closing_odds REAL,
  FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS arb_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  match_id TEXT NOT NULL,
  edge_pct REAL NOT NULL,
  legs_json TEXT NOT NULL,
  noted INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tt_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  match_id TEXT,
  message TEXT NOT NULL,
  payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_live_snapshots_match_ts ON live_snapshots(match_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_bets_match_ts ON bets(match_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_bets_result ON bets(result);
CREATE INDEX IF NOT EXISTS idx_arb_ts ON arb_alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_tt_events_ts ON tt_events(ts DESC);
