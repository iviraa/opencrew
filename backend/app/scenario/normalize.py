"""The shapes the chat cards send: canonical kind names, their default knob names, and dotted knob paths resolved into params."""
import copy

from app.config import ASSUMPTIONS

# the frontend's names are canonical; the longer ones stay as aliases
ALIASES = {"change_assumptions": "assumption", "apply_rule": "rule", "replay": "replay_year", "history_replay": "replay_year", "event": "event",
           "shift_window": "shift_window", "assumption": "assumption", "exclude_partner": "exclude_partner", "add_project": "add_project",
           "cancel_project": "cancel_project", "rule": "rule", "capacity": "capacity", "budget": "budget", "storm": "storm",
           "replay_year": "replay_year", "compose": "compose", "swap_partner": "swap_partner", "best_windows": "best_windows", "sensitivity": "sensitivity"}
QUARTERS = ("Q1", "Q2", "Q3", "Q4")


def kind_of(kind):
    k = ALIASES.get(str(kind or "").strip().lower())
    if not k:
        raise ValueError(f"unknown experiment {kind!r}; use one of {', '.join(sorted(set(ALIASES.values())))}")
    return k


def set_path(params, path, value):
    """'changes.0.months' -> params['changes'][0]['months']; numeric keys index lists."""
    keys = str(path).split(".")
    cur = params
    for k, nxt in zip(keys[:-1], keys[1:]):
        idx = int(k) if isinstance(cur, list) else k
        if isinstance(cur, list):
            while len(cur) <= idx:
                cur.append({})
            if not isinstance(cur[idx], (dict, list)):
                cur[idx] = [] if nxt.isdigit() else {}
            cur = cur[idx]
        else:
            if not isinstance(cur.get(idx), (dict, list)):
                cur[idx] = [] if nxt.isdigit() else {}
            cur = cur[idx]
    last = keys[-1]
    if isinstance(cur, list):
        i = int(last)
        while len(cur) <= i:
            cur.append(None)
        cur[i] = value
    else:
        cur[last] = value
    return params


def resolve(params):
    """Copy the params with every dotted key folded into the nested place it names."""
    out = copy.deepcopy(dict(params or {}))
    for k in [k for k in out if "." in str(k)]:
        v = out.pop(k)
        set_path(out, k, v)
    return out


def place_of(v):
    """A place knob is {lon, lat}, a [lon, lat] pair, or a name."""
    if isinstance(v, dict) and v.get("lon") is not None and v.get("lat") is not None:
        return float(v["lon"]), float(v["lat"]), None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return float(v[0]), float(v[1]), None
    if isinstance(v, str) and v.strip():
        return None, None, v.strip()
    return None, None, None


def assumption_overrides(p):
    """{name, pct} or {key, low, high | value} or {overrides: {...}} -> {key: {low, high}}."""
    if p.get("overrides") or p.get("assumptions"):
        raw = p.get("overrides") or p.get("assumptions")
        return {k: _range(v) for k, v in raw.items() if k in ASSUMPTIONS}
    key = p.get("name") or p.get("key")
    if not key:
        return {}
    if key not in ASSUMPTIONS:
        raise ValueError(f"{key!r} is not a cost assumption; the known ones are " + ", ".join(sorted(ASSUMPTIONS)))
    base = ASSUMPTIONS[key]
    if p.get("pct") is not None:
        if not -90 <= float(p["pct"]) <= 500:
            raise ValueError("percent changes are limited to -90% to +500%")
        f = 1 + float(p["pct"]) / 100
        return {key: {"low": round(float(base["low"]) * f, 4), "high": round(float(base["high"]) * f, 4)}}
    if p.get("value") is not None:
        return {key: _range(p["value"])}
    if p.get("low") is not None or p.get("high") is not None:
        return {key: {"low": float(p.get("low", base["low"])), "high": float(p.get("high", base["high"]))}}
    return {}


def _range(v):
    return {"low": float(v), "high": float(v)} if isinstance(v, (int, float)) else {end: float(v[end]) for end in ("low", "high") if end in v}


def quarter_of(p):
    """{quarter: 'Q2', year: 2027} or {quarter: '2027Q2'} -> '2027Q2'; None when unset."""
    q = str(p.get("quarter") or "").strip().upper()
    if not q:
        return None
    if q in QUARTERS:
        y = p.get("year")
        return f"{int(y)}{q}" if y else None
    return q


def storm_event(p):
    """A storm change as the storm lab's event: lon/lat from the place knob, else the name for it to locate."""
    lon, lat, label = place_of(p.get("place"))
    if lon is None and p.get("lon") is not None and p.get("lat") is not None:
        lon, lat = float(p["lon"]), float(p["lat"])
    ev = {"kind": "storm", "date": p.get("date") or None, "category": p.get("category") or p.get("cat") or 3}
    if lon is not None:
        ev["lon"], ev["lat"] = lon, lat
    if label:
        ev["place"] = label
    if p.get("state"):
        ev["state"] = p["state"]
    if p.get("radius_km"):
        ev["radius_km"] = float(p["radius_km"])
    if p.get("max_wind_mph"):
        ev["max_wind_mph"] = float(p["max_wind_mph"])
    for k in ("heading_deg", "speed_mph"):
        if p.get(k) is not None:
            ev[k] = float(p[k])
    if p.get("historical"):
        return {"kind": "historical", "name": str(p["historical"])}
    if lon is None and not label:
        raise ValueError("a storm needs a place: click the map or name a county or city")
    return ev
