"use client";

import { useEffect, useMemo, useState } from "react";
import type { AdminSession } from "@/lib/adminAuth";
import type { TTEvent, TTEvalResponse, TTLiveMatch, TTMetrics } from "@/lib/ttTypes";
import {
  ttAddManualMatch,
  ttEvaluate,
  ttEvents,
  ttLive,
  ttLogBet,
  ttMetrics,
  ttSettleBet,
} from "@/lib/api";

const emptyMetrics: TTMetrics = {
  bankroll: 0,
  total_pnl: 0,
  today_pnl: 0,
  open_bets: 0,
  settled_bets: 0,
  win_rate: null,
  hard_pass_rate: null,
  arb_alerts_today: 0,
};

export default function TableTennisPanel({ session }: { session: AdminSession }) {
  const [metrics, setMetrics] = useState<TTMetrics>(emptyMetrics);
  const [matches, setMatches] = useState<TTLiveMatch[]>([]);
  const [events, setEvents] = useState<TTEvent[]>([]);
  const [selected, setSelected] = useState("");
  const [prob, setProb] = useState(0.8);
  const [oddsA, setOddsA] = useState(1.5);
  const [bookA, setBookA] = useState(2.05);
  const [bookB, setBookB] = useState(2.05);
  const [stake, setStake] = useState(10);
  const [book, setBook] = useState("manual");
  const [evalOut, setEvalOut] = useState<TTEvalResponse | null>(null);
  const [lastBetId, setLastBetId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const current = useMemo(
    () => matches.find((m) => m.match_id === selected) || matches[0] || null,
    [matches, selected]
  );

  async function refreshAll() {
    setError("");
    try {
      const [m, l, e] = await Promise.all([
        ttMetrics(session.token),
        ttLive(session.token),
        ttEvents(session.token, 100),
      ]);
      setMetrics(m as unknown as TTMetrics);
      const incoming = ((l.matches as TTLiveMatch[]) || []).map((x) => ({ ...x, status: x.status || "watching" }));
      setMatches(incoming);
      setEvents((e.events as TTEvent[]) || []);
      setSelected((old) => old || incoming[0]?.match_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.token]);

  async function runEvaluate() {
    if (!current) return;
    setBusy(true);
    setError("");
    try {
      const leaderIsA = current.sets_a > current.sets_b || (current.sets_a === current.sets_b && current.points_a >= current.points_b);
      const res = (await ttEvaluate(session.token, {
        match_id: current.match_id,
        best_of: current.best_of,
        sets_leader: leaderIsA ? current.sets_a : current.sets_b,
        sets_trailer: leaderIsA ? current.sets_b : current.sets_a,
        points_leader: leaderIsA ? current.points_a : current.points_b,
        points_trailer: leaderIsA ? current.points_b : current.points_a,
        leader_is_a: leaderIsA,
        prob_reach_2_0_within_4_points: prob,
        offered_odds: oddsA,
        book_a_odds: bookA,
        book_b_odds: bookB,
        model_adjust: 0,
        sets_a: current.sets_a,
        sets_b: current.sets_b,
        points_a: current.points_a,
        points_b: current.points_b,
      })) as unknown as TTEvalResponse;
      setEvalOut(res);
      setMatches((old) => old.map((m) => m.match_id === current.match_id ? {
        ...m,
        status: res.evaluation.decision === "bet" ? "bet" : "skip",
        prob_2_0: prob,
        last_eval: res.evaluation.decision,
      } : m));
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addManualMatch() {
    const eventName = window.prompt("Event / league name", "Manual watch");
    if (!eventName) return;
    const playerA = window.prompt("Player A");
    if (!playerA) return;
    const playerB = window.prompt("Player B");
    if (!playerB) return;
    setBusy(true);
    try {
      const out = await ttAddManualMatch(session.token, {
        event_name: eventName,
        player_a: playerA,
        player_b: playerB,
        best_of: 5,
        sets_a: 0,
        sets_b: 0,
        points_a: 0,
        points_b: 0,
      });
      await refreshAll();
      if (out.match_id) setSelected(String(out.match_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function logManualBet() {
    if (!current || !evalOut) {
      setError("Run an evaluation first so the logged record includes the evaluation snapshot.");
      return;
    }
    const selection = window.prompt("Selection / side", current.player_a);
    if (!selection) return;
    setBusy(true);
    try {
      const out = await ttLogBet(session.token, {
        match_id: current.match_id,
        book,
        market: "manual",
        selection,
        odds: oddsA,
        stake,
        evaluation: evalOut.evaluation,
      });
      setLastBetId(String(out.bet_id || ""));
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function settleLastBet() {
    if (!lastBetId) {
      setError("No bet logged in this browser session yet.");
      return;
    }
    const result = (window.prompt("Result: win, loss, void, or cashout", "win") || "").toLowerCase();
    if (!result) return;
    const pnlRaw = window.prompt("P/L amount for this bet", result === "win" ? String(stake * Math.max(0, oddsA - 1)) : String(-stake));
    if (pnlRaw == null) return;
    const pnl = Number(pnlRaw);
    if (!Number.isFinite(pnl)) {
      setError("P/L must be a number.");
      return;
    }
    setBusy(true);
    try {
      await ttSettleBet(session.token, lastBetId, { result, pnl });
      setLastBetId(null);
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function exportDayLog() {
    const rows = [
      ["ts", "event_type", "match_id", "message"],
      ...events.map((e) => [e.ts, e.event_type, e.match_id || "", e.message]),
    ];
    const csv = rows
      .map((row) => row.map((v) => `"${String(v).replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tabletennis-events-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="tt-root">
      <header className="tt-head">
        <div>
          <span className="eyebrow">Owner module</span>
          <h1>TableTennisAI</h1>
          <p>Decision-support workspace · persistence is live · no wager placement endpoint exists.</p>
        </div>
        <div className="tt-pill">{session.username}</div>
      </header>

      {error && <div className="admin-banner-err">{error}</div>}

      <section className="tt-metrics">
        <Metric label="Bankroll" value={`$${Number(metrics.bankroll || 0).toFixed(2)}`} />
        <Metric label="Total P/L" value={`${metrics.total_pnl >= 0 ? "+" : ""}${Number(metrics.total_pnl || 0).toFixed(2)}`} tone={metrics.total_pnl >= 0 ? "good" : "bad"} />
        <Metric label="Today P/L" value={`${metrics.today_pnl >= 0 ? "+" : ""}${Number(metrics.today_pnl || 0).toFixed(2)}`} />
        <Metric label="Open bets" value={String(metrics.open_bets || 0)} />
        <Metric label="Settled" value={String(metrics.settled_bets || 0)} />
        <Metric label="Win rate" value={metrics.win_rate == null ? "—" : `${(metrics.win_rate * 100).toFixed(0)}%`} />
        <Metric label="Arb alerts" value={String(metrics.arb_alerts_today || 0)} />
        <Metric label="Hard-pass rate" value={metrics.hard_pass_rate == null ? "—" : `${(metrics.hard_pass_rate * 100).toFixed(0)}%`} />
      </section>

      <div className="tt-grid">
        <section className="tt-card">
          <div className="tt-card-head">
            <h3>Live board</h3>
            <span className="muted">feed adapter next · manual board works now</span>
          </div>
          <div className="tt-match-list">
            {matches.length === 0 && (
              <div className="tt-empty">No live matches in the local store. Add a manual match or wire the feed adapter.</div>
            )}
            {matches.map((m) => (
              <button
                key={m.match_id}
                type="button"
                className={`tt-match ${selected === m.match_id ? "on" : ""}`}
                onClick={() => {
                  setSelected(m.match_id);
                  if (m.prob_2_0 != null) setProb(m.prob_2_0);
                }}
              >
                <div className="tt-match-top">
                  <span>{m.event_name}</span>
                  <span className={`st st-${m.status}`}>{m.status}</span>
                </div>
                <strong>{m.player_a} vs {m.player_b}</strong>
                <div className="tt-score">Sets {m.sets_a}-{m.sets_b} · Pts {m.points_a}-{m.points_b}{m.prob_2_0 != null && ` · P(2-0) ${(m.prob_2_0 * 100).toFixed(0)}%`}</div>
              </button>
            ))}
          </div>
          <div className="tt-actions-row">
            <button type="button" className="ghost-btn" onClick={refreshAll} disabled={busy}>Refresh feed</button>
            <button type="button" className="ghost-btn" onClick={addManualMatch} disabled={busy}>Add manual match</button>
          </div>
        </section>

        <section className="tt-card">
          <h3>Evaluate</h3>
          {!current ? (
            <p className="muted">Select or add a match first.</p>
          ) : (
            <>
              <p className="tt-line"><strong>{current.player_a} vs {current.player_b}</strong><br />Sets {current.sets_a}-{current.sets_b} · BO{current.best_of}</p>
              <label>P(reach 2-0 within next 4 points)<input type="number" min={0} max={1} step={0.01} value={prob} onChange={(e) => setProb(Number(e.target.value))} /></label>
              <label>Offered odds<input type="number" min={1.01} step={0.01} value={oddsA} onChange={(e) => setOddsA(Number(e.target.value))} /></label>
              <div className="tt-two">
                <label>Book A odds<input type="number" min={1.01} step={0.01} value={bookA} onChange={(e) => setBookA(Number(e.target.value))} /></label>
                <label>Book B odds<input type="number" min={1.01} step={0.01} value={bookB} onChange={(e) => setBookB(Number(e.target.value))} /></label>
              </div>
              <div className="tt-two">
                <label>Manual log stake<input type="number" min={0.01} step={0.01} value={stake} onChange={(e) => setStake(Number(e.target.value))} /></label>
                <label>Book<input value={book} onChange={(e) => setBook(e.target.value)} /></label>
              </div>
              <div className="tt-actions-row">
                <button type="button" onClick={runEvaluate} disabled={busy}>{busy ? "Working…" : "Run hard gate"}</button>
                <button type="button" className="ghost-btn" onClick={logManualBet} disabled={busy || !evalOut}>Log bet</button>
                <button type="button" className="ghost-btn" onClick={settleLastBet} disabled={busy || !lastBetId}>Settle last logged</button>
              </div>
            </>
          )}

          {evalOut && (
            <div className={`tt-result ${evalOut.evaluation.decision}`}>
              <div className="tt-decision">{evalOut.evaluation.decision.toUpperCase()}</div>
              <div>hard_pass={String(evalOut.evaluation.hard_pass)} · final={evalOut.evaluation.final_score} · stake_pct={evalOut.evaluation.stake_pct}</div>
              <div className="tt-reasons">{evalOut.evaluation.reasons.join(" · ")}</div>
              {evalOut.evaluation.features?.value_edge_pct != null && <div className="tt-reasons">value edge: {String(evalOut.evaluation.features.value_edge_pct)}%</div>}
              {evalOut.arb && <div className="tt-arb">ARB alert: {JSON.stringify(evalOut.arb)}</div>}
              <div className="tt-human">{evalOut.human_action}</div>
            </div>
          )}
        </section>

        <section className="tt-card">
          <div className="tt-card-head">
            <h3>Ops / event log</h3>
            <button type="button" className="ghost-btn" onClick={exportDayLog}>Export CSV</button>
          </div>
          <p className="muted">AI match analysis remains a separate next step. This panel does not pretend demo data is live.</p>
          <ul className="tt-log">
            {events.length === 0 && <li className="muted">No events yet.</li>}
            {events.map((event) => <li key={event.id}><span>{new Date(event.ts).toLocaleTimeString()}</span> {event.message}</li>)}
          </ul>
        </section>
      </div>

      <style jsx>{`
        .tt-root { color: var(--text); }
        .tt-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:18px; }
        .tt-head h1 { margin:4px 0 4px; font-size:28px; }
        .tt-head p { color:var(--muted); margin:0; }
        .tt-pill { background:#c4a35a; color:#111; font-weight:800; padding:7px 12px; border-radius:999px; font-size:12px; }
        .tt-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-bottom:14px; }
        .tt-grid { display:grid; grid-template-columns:1.05fr 1fr 1fr; gap:12px; }
        .tt-card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; min-width:0; }
        .tt-card h3 { margin:0 0 10px; font-size:15px; }
        .tt-card-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; }
        .tt-card-head h3 { margin:0; }
        .tt-match-list { display:flex; flex-direction:column; gap:7px; max-height:350px; overflow:auto; }
        .tt-match { text-align:left; background:rgba(255,255,255,.025); border:1px solid var(--line); color:inherit; border-radius:9px; padding:9px 10px; cursor:pointer; }
        .tt-match.on { border-color:#c4a35a; }
        .tt-match-top { display:flex; justify-content:space-between; gap:10px; color:var(--muted); font-size:11px; }
        .tt-score { margin-top:4px; color:var(--muted); font-size:12px; }
        .st { text-transform:uppercase; letter-spacing:.04em; font-size:10px; }
        .st-bet { color:#6dffa8; } .st-skip { color:#ff8e8e; } .st-watching { color:#8ecbff; }
        .tt-empty { color:var(--muted); border:1px dashed var(--line); border-radius:9px; padding:14px; font-size:13px; }
        label { display:flex; flex-direction:column; gap:5px; margin-bottom:8px; color:var(--muted); font-size:12px; }
        input { background:rgba(0,0,0,.25); border:1px solid var(--line); border-radius:8px; color:var(--text); padding:8px 9px; }
        .tt-two { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
        .tt-actions-row { display:flex; flex-wrap:wrap; gap:7px; margin-top:10px; }
        .tt-actions-row button { border:1px solid var(--line); background:#c4a35a; color:#111; border-radius:8px; padding:8px 11px; font-weight:700; cursor:pointer; }
        .tt-actions-row button.ghost-btn, .tt-card-head .ghost-btn { background:transparent; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:7px 10px; cursor:pointer; }
        button:disabled { opacity:.45; cursor:not-allowed; }
        .tt-result { margin-top:12px; padding:10px; border:1px solid var(--line); border-radius:9px; background:rgba(0,0,0,.22); font-size:12px; }
        .tt-result.bet { border-color:#2f6f4e; } .tt-result.skip { border-color:#6f2f2f; }
        .tt-decision { font-size:17px; font-weight:800; letter-spacing:.06em; margin-bottom:4px; }
        .tt-reasons,.tt-human,.tt-arb { margin-top:6px; color:var(--muted); } .tt-arb { color:#ffd27a; }
        .tt-line { font-size:13px; }
        .tt-log { list-style:none; padding:0; margin:10px 0 0; max-height:350px; overflow:auto; font-size:12px; color:var(--muted); }
        .tt-log li { padding:7px 0; border-bottom:1px solid rgba(255,255,255,.05); }
        .tt-log span { color:var(--text); margin-right:6px; }
        .muted { color:var(--muted); font-size:12px; }
        @media (max-width:1100px) { .tt-grid { grid-template-columns:1fr; } }
      `}</style>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className={`metric ${tone || ""}`}>
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      <style jsx>{`
        .metric { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:9px 10px; }
        .k { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
        .v { font-size:16px; font-weight:700; margin-top:3px; }
        .good .v { color:#6dffa8; } .bad .v { color:#ff8e8e; }
      `}</style>
    </div>
  );
}
