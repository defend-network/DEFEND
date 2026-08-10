export type TTLiveMatch = {
  match_id: string;
  event_name: string;
  player_a: string;
  player_b: string;
  sets_a: number;
  sets_b: number;
  points_a: number;
  points_b: number;
  best_of: number;
  status: "watching" | "alert" | "bet" | "skip" | "settled";
  prob_2_0: number | null;
  last_eval?: string;
};

export type TTMetrics = {
  bankroll: number;
  total_pnl: number;
  today_pnl: number;
  open_bets: number;
  settled_bets: number;
  win_rate: number | null;
  hard_pass_rate: number | null;
  arb_alerts_today: number;
};

export type TTEvaluation = {
  hard_pass: boolean;
  hard_failures: string[];
  soft_score: number;
  model_adjust: number;
  final_score: number;
  decision: string;
  stake_pct: number;
  reasons: string[];
  features: Record<string, unknown>;
};

export type TTEvalResponse = {
  evaluation: TTEvaluation;
  arb: Record<string, unknown> | null;
  hedge: Record<string, unknown> | null;
  human_action: string;
};

export type TTEvent = {
  id: number;
  ts: string;
  event_type: string;
  match_id?: string | null;
  message: string;
  payload_json?: string | null;
};
