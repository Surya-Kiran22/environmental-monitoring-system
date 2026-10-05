"""Epsilon-greedy contextual bandit that ranks investigation recommendations.

Context = "<domain>:<alert category>". Arms are candidate follow-up actions. Reward comes from
officers marking a recommendation useful (1) or not useful (0). The bandit only *suggests*;
humans decide.
"""
from __future__ import annotations

import random

from ..config import BANDIT_EPSILON
from ..database import BanditArm

ARMS = {
    "air": ["Dispatch field inspection to the monitoring area", "Review upwind registered sources (potential contributors)",
            "Request PM analyser flow/tape check", "Increase monitoring frequency for 48 h", "Prepare public health advisory draft for approval"],
    "water": ["Collect grab sample for laboratory confirmation", "Wipe and verify turbidity probe against grab sample",
              "Inspect upstream outfalls (sources requiring investigation)", "Increase sampling frequency to 15 min", "Notify downstream water-treatment operator for awareness"],
    "noise": ["Schedule night-time field noise survey", "Check complaints register for the area",
              "Review nearby venues (sources requiring investigation)", "Verify sound level meter calibration and windscreen"],
    "sensor": ["Perform zero/span calibration check", "Dispatch technician to inspect sensor", "Cross-check against nearest station", "Mark readings invalid pending verification"],
}


def _rows(db, context: str, domain: str):
    rows = {r.arm: r for r in db.query(BanditArm).filter(BanditArm.context == context).all()}
    for arm in ARMS[domain]:
        if arm not in rows:
            r = BanditArm(context=context, arm=arm, pulls=0, reward_sum=0.0)
            db.add(r)
            rows[arm] = r
    db.flush()
    return rows


def recommend(db, domain: str, category: str, seed: str | None = None, k: int = 3) -> dict:
    domain = domain if domain in ARMS else "air"
    context = f"{domain}:{category}"
    rows = _rows(db, context, domain)
    rng = random.Random(seed)
    def mean(r):  # Beta(1,1) prior -> optimistic 0.5 start
        return (r.reward_sum + 1) / (r.pulls + 2)
    ranked = sorted(rows.values(), key=mean, reverse=True)
    explore = rng.random() < BANDIT_EPSILON
    chosen = rng.choice(ranked) if explore else ranked[0]
    chosen.pulls += 1
    db.commit()
    return {"context": context, "policy": "epsilon-greedy", "epsilon": BANDIT_EPSILON, "mode": "explore" if explore else "exploit",
            "recommended_action": chosen.arm,
            "ranked": [{"action": r.arm, "expected_usefulness": round(mean(r), 3), "pulls": r.pulls} for r in ranked[:k]]}


def feedback(db, context: str, arm: str, useful: bool) -> None:
    domain = context.split(":")[0]
    rows = _rows(db, context, domain if domain in ARMS else "air")
    if arm in rows:
        rows[arm].reward_sum += 1.0 if useful else 0.0
        if rows[arm].pulls == 0:
            rows[arm].pulls = 1
        db.commit()
