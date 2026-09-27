"""Refuse a planner file whose shape drifted: missing columns, empty ids, dates that stopped parsing, a row count that jumped."""
import re

import pandas as pd

from app.ingest.national.common import to_date


def _sheets(x, spec):
    if isinstance(spec, re.Pattern):
        return [s for s in x.sheet_names if spec.match(s)]
    if isinstance(spec, int):
        return [x.sheet_names[spec]] if spec < len(x.sheet_names) else []
    return [spec] if spec in x.sheet_names else []


def _has(columns, want):
    return any(want.match(str(c)) for c in columns) if isinstance(want, re.Pattern) else want in columns


def _col(columns, want):
    return next((c for c in columns if want.match(str(c))), None) if isinstance(want, re.Pattern) else want


def validate(path, src, baseline_rows=None):
    """{ok, message, sheets, missing_columns, extra_columns, row_count, id_fill, date_parse, sample_issues}; never raises on bad files."""
    out = {"ok": False, "message": "", "sheets": [], "missing_columns": [], "extra_columns": [], "row_count": 0, "id_fill": 0.0,
           "date_parse": 0.0, "sample_issues": []}
    try:
        x = pd.ExcelFile(path)
    except Exception as e:  # not a workbook at all
        out["message"] = f"could not open the file: {str(e)[:120]}"
        return out
    sheets = _sheets(x, src.sheet)
    out["sheets"] = sheets
    if not sheets:
        out["message"] = f"expected sheet {getattr(src.sheet, 'pattern', src.sheet)!r} not found; sheets are {x.sheet_names[:8]}"
        return out
    frames = [pd.read_excel(x, s, header=src.header) for s in sheets]
    cols = list(frames[0].columns)
    missing = [getattr(c, "pattern", c) for c in src.columns if not _has(cols, c)]
    known = {getattr(c, "pattern", c) for c in src.columns}
    out["missing_columns"] = missing
    out["extra_columns"] = [str(c) for c in cols if str(c) not in known and not str(c).startswith("Unnamed")][:12]
    if missing:
        out["message"] = f"columns changed: missing {missing}"
        return out
    df = pd.concat(frames, ignore_index=True)
    idc, dtc = _col(cols, src.id_column), _col(cols, src.date_column)
    ids = df[idc]
    rows = int(ids.notna().sum())
    out["row_count"] = rows
    if rows == 0:
        out["message"] = "the file has no rows with an id"
        return out
    out["id_fill"] = round(rows / max(len(df), 1), 3)
    dates = df.loc[ids.notna(), dtc]
    given = dates[dates.notna() & (dates.astype(str).str.strip() != "")]
    parsed = sum(1 for v in given if to_date(_us(v)) is not None)
    out["date_parse"] = round(parsed / len(given), 3) if len(given) else 1.0
    if out["id_fill"] < src.id_min_fill:
        out["message"] = f"only {out['id_fill']:.0%} of rows carry an id (expected {src.id_min_fill:.0%}+)"
        return out
    if out["date_parse"] < src.date_min_parse:
        out["sample_issues"] = [str(v)[:40] for v in given if to_date(_us(v)) is None][:5]
        out["message"] = f"only {out['date_parse']:.0%} of in-service dates parse (expected {src.date_min_parse:.0%}+); e.g. {out['sample_issues']}"
        return out
    if baseline_rows and not (0.3 * baseline_rows <= rows <= 3 * baseline_rows):
        out["message"] = f"row count {rows} is far from the last edition's {baseline_rows}"
        return out
    out["ok"] = True
    out["message"] = f"{rows} rows, ids {out['id_fill']:.0%} filled, dates {out['date_parse']:.0%} parse"
    return out


def _us(v):
    """PJM's M/D/YYYY strings and plain years read as dates too."""
    if isinstance(v, str):
        s = v.strip()
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        if re.fullmatch(r"20\d\d(\.0)?", s):
            return f"{s[:4]}-12-31"
    if isinstance(v, (int, float)) and 2000 <= float(v) <= 2100:
        return f"{int(v)}-12-31"
    return v
