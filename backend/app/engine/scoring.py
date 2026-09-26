from app.config import TIER_WEIGHT, TIERS


def tier_for(distance_m, touches=False):
    if touches or distance_m <= 0:
        return "crossing"
    for name, limit in TIERS[1:]:
        if distance_m < limit:
            return name
    return None


def time_overlap(a_start, a_end, b_start, b_end):
    inter = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    shorter = min((a_end - a_start).total_seconds(), (b_end - b_start).total_seconds())
    if inter <= 0 or shorter <= 0:
        return 0.0
    return min(inter / shorter, 1.0)


def time_factor(overlap):
    if overlap >= 0.5:
        return 1.0
    return 0.5 if overlap > 0 else 0.2


def score(tier, overlap, risk=0.0, vulnerability=0.0):
    return TIER_WEIGHT[tier] * time_factor(overlap) * (1 + risk + vulnerability)
