from app.config import DRIVE_FACTOR, MAX_DRIVE_MIN, PHASE_MISMATCH, PHASE_SHARE, TIER_WEIGHT, TIERS


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


def phase_share(a_phase, b_phase):
    if not a_phase or not b_phase:
        return None  # long-range jobs have no phase
    return PHASE_SHARE.get(tuple(sorted((a_phase, b_phase))), PHASE_MISMATCH)


def too_far(drive_min):
    return drive_min is not None and drive_min > MAX_DRIVE_MIN


def score(tier, overlap, risk=0.0, vulnerability=0.0, phase_factor=1.0, drive_min=None):
    drive = DRIVE_FACTOR if too_far(drive_min) else 1.0
    return TIER_WEIGHT[tier] * time_factor(overlap) * (1 + risk + vulnerability) * phase_factor * drive
