import uno  
import unohelper
import re
import math
import traceback
from pint import UnitRegistry

ureg = UnitRegistry()
ureg.define("inch = 0.0254 * meter")
Quantity = ureg.Quantity

PREFERRED_UNITS = [
    ureg.newton,
    ureg.joule,
    ureg.watt,
    ureg.pascal,
    ureg.psi,
    ureg.pound_force,
]

GLOBAL_VARIABLES = {}
_formula_updater = None

class FormulaUpdater(unohelper.Base):
    def __init__(self, doc):
        self.doc = doc
        self.running = False
    def getTypes(self):
        return (
            uno.getTypeByName(
                "com.sun.star.util.XModifyListener"
            ),
        )
    def modified(self, event):
        if self.running:
            return
        self.running = True
        try:
            CalculateFormula()
        except Exception:
            traceback.print_exc()
        finally:
            self.running = False
    def disposing(self, event):
        pass

TOKEN_RE = re.compile(r'''
(:=)
|(<>|<=|>=|=|<|>)
|(over|times|cdot|sqrt|sup|sub)
|("(?:[^"\\]|\\.)*")  #start of edits rn ! ! ! !!
|(\d+\.\d+|\d+)
|([A-Za-z][A-Za-z0-9_']*)
|(\^|\+|-|\*|/|\(|\)|\[|\]|\{|\}|,)
''', re.VERBOSE)

TRIG_FUNCTIONS = {
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "atan2",
    "min",
    "max",
}

MATHEMATICAL_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

IDENTIFIER_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_']*$"
)

def is_identifier(token):
    return bool(
        token and IDENTIFIER_RE.match(token)
    )

def is_string_literal(token):
    return (
        isinstance(token, str)
        and len(token) >= 2
        and token.startswith('"')
        and token.endswith('"')
    )

def parse_string_literal(token):
    if not is_string_literal(token):
        raise ValueError(
            "Invalid string literal: " + str(token)
        )
    try:
        return bytes(
            token[1:-1],
            "utf-8"
        ).decode("unicode_escape")
    except Exception:
        return token[1:-1]

def normalize_subscripts(expr):
    def encode_subscript(match):
        base = match.group(1)
        subscript = match.group(2)
        if not subscript.strip():
            raise SyntaxError(
                f"Empty subscript in {base}_()"
            )
        encoded = subscript.encode("utf-8").hex()
        return base + "__sub__" + encoded
    expr = re.sub(
        r"([A-Za-z][A-Za-z0-9_']*)_\(([^()]*)\)",
        encode_subscript,
        expr
    )
    expr = re.sub(
        r'([A-Za-z][A-Za-z0-9]*)\s*sub\s*\{([^}]+)\}',
        r'\1_\2',
        expr
    )
    expr = re.sub(
        r'([A-Za-z][A-Za-z0-9_]*|[A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9]+)_\{([^}]+)\}',
        r'\1_\2',
        expr
    )
    return expr

def tokenize(text):
    text = re.sub(r"%pi\b", "pi", text)
    text = normalize_subscripts(text)
    tokens = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise SyntaxError(
                "Unexpected character: " + text[pos]
            )
        tokens.append(m.group(0))
        pos = m.end()
    return tokens

def compare_values(left, right, operator):
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        if left.dimensionality != right.dimensionality:
            raise ValueError(
                "Cannot compare incompatible units: "
                f"{left.units} and {right.units}"
            )
        right = right.to(left.units)
        left = left.magnitude
        right = right.magnitude
    elif isinstance(left, Quantity):
        if not left.dimensionless:
            raise ValueError(
                "Cannot compare a quantity with a plain number"
            )
        left = left.magnitude
    elif isinstance(right, Quantity):
        if not right.dimensionless:
            raise ValueError(
                "Cannot compare a plain number with a quantity"
            )
        right = right.magnitude
    if operator == "=":
        return left == right
    if operator == "<>":
        return left != right
    if operator == "<":
        return left < right
    if operator == ">":
        return left > right
    if operator == "<=":
        return left <= right
    if operator == ">=":
        return left >= right
    raise SyntaxError(
        "Unknown comparison operator: " + operator
    )

class Parser:
    def __init__(self, tokens, variables):
        self.tokens = tokens
        self.i = 0
        self.variables = variables
    def peek(self):
        if self.i >= len(self.tokens):
            return None
        return self.tokens[self.i]
    def eat(self, expected=None):
        token = self.peek()
        if expected and token != expected:
            raise SyntaxError(
                "Expected " + expected
            )
        self.i += 1
        return token
    def comparison(self):
        left = self.expression()
        tok = self.peek()
        if tok in ("=", "<>", "<", ">", "<=", ">="):
            operator = self.eat()
            right = self.expression()
            return compare_values(
                left,
                right,
                operator
            )
        return left

    def expression(self):     
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.eat()
            rhs = self.term()
            if op == "+":
                value += rhs
            else:
                value -= rhs
        return value
    def starts_factor(self, tok):
        if tok is None:
            return False
        if tok in ("(", "pi", "e"):
            return True
        if tok[0].isdigit():
            return True
        if is_identifier(tok):
            return True
        return False

    def term(self):
        value = self.factor()
        while True:
            tok = self.peek()
            if tok in ("*", "times", "cdot"):
                self.eat(tok)
                rhs = self.factor()
                value = value * rhs
            elif tok in ("/", "over"):
                self.eat(tok)
                rhs = self.factor()
                # Convert compatible units before division.
                if (
                    isinstance(value, Quantity)
                    and isinstance(rhs, Quantity)
                    and value.dimensionality == rhs.dimensionality
                ):
                    rhs = rhs.to(value.units)
                value = value / rhs
            elif self.starts_factor(tok):
                # implicit multiplication
                rhs = self.factor()
                value = value * rhs
            else:
                break
        return value
    def factor(self):
        value = self.primary()
        while self.peek() in ("^", "sup"):
            self.eat()
            if self.peek() == "{":
                self.eat("{")
                exponent = self.expression()
                self.eat("}")
            else:
                exponent = self.factor()
            value = value ** exponent
        return value

    def resolve_identifier(self, name):
        if name in self.variables:
            return self.variables[name]
        raise NameError(
            "Missing variable: [" + name + "] vars=" +
            str(list(self.variables.keys()))
        )

    def primary(self):
        tok = self.peek()
        if is_string_literal(tok):
            self.eat()
            return parse_string_literal(tok)
        if tok == "if" and self.i + 1 < len(self.tokens):   # jsut added this if statement starting more edits
            if self.tokens[self.i + 1] == "(":
                self.eat("if")
                return self.evaluate_if()
        if tok in TRIG_FUNCTIONS:
            self.eat()
            return self.evaluate_function(tok)
        if tok == "sqrt":
            self.eat("sqrt")
            if self.peek() == "{":
                self.eat("{")
                value = self.expression()
                self.eat("}")
            else:
                value = self.primary()
            return value ** 0.5
        if tok == "pi":
            self.eat()
            next_tok = self.peek()
            if (
                next_tok
                and is_identifier(next_tok)
            ):
                try:
                    unit = ureg.parse_units(next_tok)
                    if unit.dimensionality == ureg.radian.dimensionality:
                        self.eat()
                        return math.pi * unit
                except Exception:
                    pass
            return math.pi
        if tok == "e":
            self.eat()
            return math.e
        if tok == "(":
            self.eat("(")
            value = self.expression()
            self.eat(")")
            return value
        if tok == "[":
            self.eat("[")
            value = self.expression()
            self.eat("]")
            return value
        if tok == "-":
            self.eat("-")
            return -self.primary()
        if tok == "+":
            self.eat("+")
            return self.primary()   
        try:
            value = float(tok)
            self.eat()
            next_tok = self.peek()
            RESERVED = {
                "cdot",
                "times",
                "over",
                "sqrt",
                "sup",
                "sub",
            }
            if (
                next_tok
                and is_identifier(next_tok)
                and next_tok not in RESERVED
            ):
                # Variables take priority over units
                if next_tok in self.variables:
                    return value * self.variables[next_tok]
                try:
                    unit = ureg.parse_units(next_tok)
                    self.eat()
                    if self.peek() in ("^", "sup"):
                        self.eat()
                        if self.peek() == "{":
                            self.eat("{")
                            exponent = self.expression()
                            self.eat("}")
                        else:
                            exponent = self.eat()
                        unit = unit ** int(exponent)
                    return value * unit
                except Exception:
                    pass
            return value
        except ValueError:
            pass
        if is_identifier(tok):
            self.eat()
            return self.resolve_identifier(tok)
        raise SyntaxError(
            "Unexpected token: " + str(tok)
        )

    def trig_argument(self, name):
        if self.peek() == "(":
            self.eat("(")
            value = self.expression()
            self.eat(")")
            return value
        if self.peek() == "{":
            self.eat("{")
            value = self.expression()
            self.eat("}")
            return value
        return self.factor()

    def trig_value(self, name, value):
        if not isinstance(value, Quantity):
            raise ValueError(
                f"{name}() requires an angle with a unit, "
                f"such as {name}(30 deg) or {name}(4 rad)"
            )
        try:
            return value.to(ureg.radian).magnitude
        except Exception:
            raise ValueError(
                f"{name}() requires an angle unit, "
                f"such as deg or rad"
            )

    def evaluate_if(self):
        self.eat("(")
        condition = self.comparison()
        if not isinstance(condition, bool):
            raise ValueError(
                "if() condition must be a comparison"
            )
        self.eat(",")
        true_value = self.comparison()
        self.eat(",")
        false_value = self.comparison()
        self.eat(")")
        if condition:
            return true_value
        return false_value

    def evaluate_function(self, name):
        if name in ("min", "max"):
            if self.peek() != "(":
                raise SyntaxError(
                    f"{name} requires arguments: {name}(a, b)"
                )
            self.eat("(")
            values = []
            while True:
                value = self.expression()
                values.append(value)
                if self.peek() == ",":
                    self.eat(",")
                    continue
                break
            self.eat(")")
            if len(values) < 2:
                raise ValueError(
                    f"{name} requires at least two arguments"
                )
            if any(isinstance(v, Quantity) for v in values):
                if not all(isinstance(v, Quantity) for v in values):
                    raise ValueError(
                        f"{name}() arguments must all be quantities "
                        "or all be dimensionless"
                    )
                reference = values[0]
                for v in values[1:]:
                    if v.dimensionality != reference.dimensionality:
                        raise ValueError(
                            f"{name}() arguments must have compatible units"
                        )
                converted = [
                    v.to(reference.units)
                    for v in values
                ]
                if name == "min":
                    index = min(
                        range(len(converted)),
                        key=lambda i: converted[i].magnitude
                    )
                else:
                    index = max(
                        range(len(converted)),
                        key=lambda i: converted[i].magnitude
                    )
                return values[index]
            if name == "min":
                return min(values)

            return max(values)
        if name == "atan2":
            if self.peek() == "(":
                self.eat("(")
                y = self.expression()
                self.eat(",")
                x = self.expression()
                self.eat(")")
            else:
                raise SyntaxError(
                    "atan2 requires two arguments: atan2(y, x)"
                )
            if isinstance(y, Quantity):
                if not y.dimensionless:
                    raise ValueError(
                        "atan2() arguments must be dimensionless"
                    )
                y = y.magnitude
            if isinstance(x, Quantity):
                if not x.dimensionless:
                    raise ValueError(
                        "atan2() arguments must be dimensionless"
                    )
                x = x.magnitude
            return math.atan2(y, x) * ureg.radian
        value = self.trig_argument(name)
        if name in ("asin", "acos", "atan"):
            if isinstance(value, Quantity):
                if not value.dimensionless:
                    raise ValueError(
                        f"{name}() requires a dimensionless input"
                    )
                value = value.magnitude
            result = {
                "asin": math.asin,
                "acos": math.acos,
                "atan": math.atan,
            }[name](value)
            return result * ureg.radian
        if name in ("sin", "cos", "tan"):
            value = self.trig_value(name, value)
            result = {
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
            }[name](value)
            if abs(result) < 1e-12:
                result = 0.0
            return result
        raise SyntaxError("Unknown function: " + name)
    
    def find_top_level_equals(text):
        paren_depth = 0
        brace_depth = 0
        bracket_depth = 0
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth -= 1
            elif ch == "=":
                if (
                    paren_depth == 0
                    and brace_depth == 0
                    and bracket_depth == 0
                ):
                    # Don't treat <= or >= or <> as
                    # the result separator.
                    if i > 0 and text[i - 1] in "<>":
                        i += 1
                        continue
                    if i + 1 < len(text) and text[i + 1] == ">":
                        i += 1
                        continue
                    return i
            i += 1
        return None

def split_formula(formula):
    s = formula.strip()
    m = re.match(
        r'^(.*?)\s=\s"(True|False)"\s*$',
        s
    )
    if m:
        expr = m.group(1).rstrip()
        return expr, False
    if s.endswith("="):
        return s[:-1].rstrip(), True
    m = re.match(
        r'^(.*?)\s=\s.*$',
        s
    )
    if m:
        expr = m.group(1)
        return expr.rstrip(), True
    return s, False

# Sequential evaluator 
def evaluate(expr, variables):
    tokens = tokenize(expr)
    if ":=" in tokens:
        idx = tokens.index(":=")
        name = tokens[idx - 1]
        value_tokens = tokens[idx + 1:]
        parser = Parser(value_tokens, variables)
        value = parser.comparison()
        variables[name] = value
        return value
    parser = Parser(
        tokens,
        variables
    )
    return parser.comparison()

def pretty_unit(unit_obj):
    s = f"{unit_obj:~}"
    s = s.replace("foot", "ft")
    s = s.replace(" ", "")
    supers = {
        "0":"⁰",
        "1":"¹",
        "2":"²",
        "3":"³",
        "4":"⁴",
        "5":"⁵",
        "6":"⁶",
        "7":"⁷",
        "8":"⁸",
        "9":"⁹",
        "-":"⁻"
    }
    def sup(match):
        return "".join(supers[c] for c in match.group(1))
    s = re.sub(r"\*\*(-?\d+)", sup, s)
    s = s.replace("*", "·")
    return s

def candidate_display_units(raw_expr, result_q):
    units = []
    tokens = tokenize(raw_expr)
    for tok in tokens:
        if is_identifier(tok):
            try:
                u = ureg.parse_units(tok)
                units.append(u)
            except Exception:
                pass
    if not units:
        units = [
            ureg.meter,
            ureg.second,
            ureg.kilogram,
            ureg.inch,
            ureg.foot,
        ]
    candidates = []
    for u in units:
        for power in range(1, 5):
            try:
                candidate = u ** power
                if candidate.dimensionality == result_q.dimensionality:
                    candidates.append(candidate)
            except Exception:
                pass
    candidates.append(result_q.units)
    return candidates

def uses_us_units(raw_expr, variables):
    if re.search(
        r'\b(in|inch|ft|foot|feet|lbf|lb|psi)\b',
        raw_expr
    ):
        return True
    for name, value in variables.items():
        if name in raw_expr and isinstance(value, Quantity):
            unit_string = str(value.units)
            if any(u in unit_string for u in [
                "inch",
                "foot",
                "pound",
                "psi"
            ]):
                return True
    return False

def uses_si_units(raw_expr, variables):
    if re.search(
        r'\b(mm|cm|m|km|N|Pa|J|W|kg|g)\b',
        raw_expr
    ):
        return True
    for name, value in variables.items():
        if name in raw_expr and isinstance(value, Quantity):
            unit_string = str(value.units)
            if any(u in unit_string for u in [
                "meter",
                "kilogram",
                "second",
                "newton",
                "pascal"
            ]):
                return True
    return False

def choose_output_unit(raw_expr, result_q, variables):
    if not isinstance(result_q, Quantity):
        return None
    if result_q.dimensionless:
        return None
    if uses_us_units(raw_expr, variables):
        preferred = [
            ureg.psi,
            ureg.pound_force,
        ]
    else:
        preferred = [
            ureg.newton,
            ureg.joule,
            ureg.watt,
            ureg.pascal,
        ]
    for u in preferred:
        try:
            result_q.to(u)
            return u
        except:
            pass
    best = None
    best_score = None
    for u in candidate_display_units(raw_expr, result_q):
        try:
            converted = result_q.to(u)
            mag = abs(converted.magnitude)
            if mag == 0:
                continue
            score = abs(math.log10(mag))
            if best_score is None or score < best_score:
                best_score = score
                best = u
        except:
            pass
    return best

def is_comparison(expr):
    tokens = tokenize(expr)
    return any(
        tok in ("=", "<>", "<", ">", "<=", ">=")
        for tok in tokens
    )

def format_logic_result(value):
    return "True" if value else "False"

def format_result(x, target_unit=None):
    if isinstance(x, str):
        return '"' + x.replace('"', '\\"') + '"'
    if isinstance(x, Quantity):
        try:
            if x.units == ureg.radian:
                x = x.to(ureg.degree)
                return f"{x.magnitude:g} deg"
            if x.units == ureg.degree:
                return f"{x.magnitude:g} deg"
        except Exception:
            pass
        if x.dimensionless:
            return f"{x.magnitude:g}"
        if target_unit is not None:
            try:
                x = x.to(target_unit)
            except Exception:
                pass
        return f"{x.magnitude:g} {pretty_unit(x.units)}"
    if isinstance(x, bool):
        return format_logic_result(x)
    return f"{x:g}"

# LibreOffice OLE runner
def CalculateFormula(*args):
    variables = GLOBAL_VARIABLES
    doc = XSCRIPTCONTEXT.getDocument()
    doc.lockControllers()
    doc.unlockControllers()
    embedded_objects = doc.getEmbeddedObjects()
    names = list(
        embedded_objects.getElementNames()
    )
    names.reverse()
    for name in names:
        try:
            obj = embedded_objects.getByName(name)
            model = obj.EmbeddedObject.getComponent()
            formula = model.Formula.strip()
            expr, show_result = split_formula(formula)
            if ":=" in expr:
                answer = evaluate(expr, variables)
                # Only display a result if the user typed a trailing '='
                if show_result:
                    model.Formula = (
                        expr +
                        " = " +
                        format_result(
                            answer,
                            choose_output_unit(expr, answer, variables)
                        )
                    )
            elif show_result or is_comparison(expr):
                answer = evaluate(expr, variables)
                if isinstance(answer, bool):
                    model.Formula = (
                        expr +
                        " = " +
                        format_logic_result(answer)
                    )
                else:
                    target = choose_output_unit(
                        expr,
                        answer,
                        variables
                    )
                    model.Formula = (
                        expr +
                        " = " +
                        format_result(answer, target)
                    )
        except Exception as e:
            try:
                model.Formula = (
                    expr +
                    ' = "' +
                    str(e) +
                    '"'
                )
            except:
                pass

# live calculation
def StartLiveCalculation(*args):
    global _formula_updater
    doc = XSCRIPTCONTEXT.getDocument()
    _formula_updater = FormulaUpdater(doc)
    doc.addModifyListener(_formula_updater)
g_exportedScripts = (
    CalculateFormula,
    StartLiveCalculation,
)
