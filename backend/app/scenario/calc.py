"""A calculator Crewly can trust: plain arithmetic over named values, nothing else can run."""
import ast
import math
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
       ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}
MILE_KM = 1.609344


def _avg(*xs):
    xs = _flat(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _flat(xs):
    out = []
    for x in xs:
        out.extend(_flat(x) if isinstance(x, (list, tuple)) else [x])
    return out


FUNCS = {"sum": lambda *xs: sum(_flat(xs)), "min": lambda *xs: min(_flat(xs)), "max": lambda *xs: max(_flat(xs)), "avg": _avg, "abs": abs,
         "round": round, "sqrt": math.sqrt, "mi_km": lambda x: x * MILE_KM, "km_mi": lambda x: x / MILE_KM, "pct": lambda a, b: 100.0 * a / b if b else 0.0,
         "pct_change": lambda a, b: 100.0 * (b - a) / a if a else 0.0}
MAX_LEN = 400
MAX_POW = 1e6


def usd(n):
    return f"-{usd(-n)}" if n < 0 else f"${n / 1e6:.2f}M" if n >= 1e6 else f"${n / 1e3:.1f}k" if n >= 1e3 else f"${n:,.2f}"


class Unsafe(ValueError):
    pass


def _eval(node, values, steps):
    if isinstance(node, ast.Expression):
        return _eval(node.body, values, steps)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise Unsafe(f"unknown value {node.id!r}; pass it in values")
        return float(values[node.id])
    if isinstance(node, ast.List) or isinstance(node, ast.Tuple):
        return [_eval(e, values, steps) for e in node.elts]
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand, values, steps))
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        a, b = _eval(node.left, values, steps), _eval(node.right, values, steps)
        if isinstance(node.op, ast.Pow) and (abs(a) > MAX_POW or abs(b) > 64):
            raise Unsafe("power too large")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise Unsafe("division by zero")
        r = OPS[type(node.op)](a, b)
        steps.append(f"{_fmt(a)} {SYMBOL[type(node.op)]} {_fmt(b)} = {_fmt(r)}")
        return r
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
        args = [_eval(a, values, steps) for a in node.args]
        r = FUNCS[node.func.id](*args)
        steps.append(f"{node.func.id}({', '.join(_fmt(a) for a in _flat(args))}) = {_fmt(r)}")
        return r
    raise Unsafe(f"not allowed: {type(node).__name__}")


SYMBOL = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "^", ast.Mod: "%", ast.FloorDiv: "//"}


def _fmt(x):
    if isinstance(x, list):
        return "[" + ", ".join(_fmt(v) for v in x) + "]"
    return f"{x:,.4g}" if abs(x) < 1e4 else f"{x:,.0f}"


def calculate(expression, values=None):
    """Evaluate arithmetic over the given named numbers; anything beyond + - * / ^ % and the listed functions is refused."""
    expr = str(expression or "").strip()
    if not expr or len(expr) > MAX_LEN:
        raise Unsafe("expression missing or too long")
    vals = {}
    for k, v in (values or {}).items():
        if not str(k).isidentifier():
            raise Unsafe(f"bad value name {k!r}")
        vals[str(k)] = float(v)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise Unsafe(f"cannot parse: {e.msg}")
    steps = []
    result = _eval(tree, vals, steps)
    if isinstance(result, list):
        raise Unsafe("the expression must end in a single number")
    return {"expression": expr, "values": vals, "result": round(result, 6), "steps": steps[-12:], "usd": usd(result),
            "functions": sorted(FUNCS)}
