"""Storm lab: what-if storms, real-year replays and sensitivity, as findings. EXPERIMENTS lets a generic runner dispatch by kind."""
from app.stormlab.events import apply_event  # noqa: F401  the composable core: an event over job rows as they stand in the transaction


def _storm(conn, company, params):
    from app.stormlab.storm import storm_scenario
    p = dict(params or {})
    return storm_scenario(conn, company, place=p.get("place"), lon=p.get("lon"), lat=p.get("lat"), state=p.get("state"), date_=p.get("date"),
                          category=p.get("category"), max_wind_mph=p.get("max_wind_mph"), historical=p.get("historical"),
                          heading_deg=float(p.get("heading_deg", 20.0)), speed_mph=float(p.get("speed_mph", 15)))


def _replay(conn, company, params):
    from app.stormlab.replay import history_replay
    p = dict(params or {})
    return history_replay(conn, company, p.get("opportunity_ids") or [], p.get("job_ids") or [], p.get("plan_id"), p.get("years"), p.get("hazards"))


def _sensitivity(conn, company, params):
    from app.stormlab.sensitivity import sensitivity
    p = dict(params or {})
    return sensitivity(conn, company, p["opportunity_id"], p.get("metric", "savings"), p.get("knobs"), p.get("month"))


EXPERIMENTS = {"storm": _storm, "replay": _replay, "sensitivity": _sensitivity}  # kind -> callable(conn, company, params) -> finding
