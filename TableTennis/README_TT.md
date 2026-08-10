# Table tennis — owner-only betting assist

## Rules encoded
- HARD: path to **2-0 in sets** only if not already 2-0, trailer still on 0 sets,
  and P(reach 2-0 within next 4 points) >= 0.80
- SOFT: second-set margin momentum, rank delta, H2H
- Model adjust clipped (±0.08 default); cannot override hard fail
- Arb / hedge calculators are **alerts only** — humans place all bets

## Run demo
```bash
pip install pyyaml
python tt_engine.py
```

## Wire into DEFEND
1. Copy folder into DEFEND32B/tt_betting/
2. Register tools only in admin/owner policy (deny in ProductionPolicy for public)
3. Live UI: feed sets/points + your prob estimate (or later a trained model)
4. Partner on phone takes hedge legs when arb/hedge alert fires

## Data later
- Import SCORE/Kaggle CSV + ITTF for priors / Elo
- Train prob_reach_2_0_within_4_points model chronologically
- Never let LLM invent live scores; scrape/API → structured state only
