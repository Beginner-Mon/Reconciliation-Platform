import re
import statistics

from .position import _layout, _lines, _numbers, _plain, _terms

SCALARS = (
    "doc_number", "doc_date", "order_reference", "seller", "seller_tax_code",
    "buyer", "buyer_tax_code", "subtotal", "discount_amount", "tax_amount", "total_amount",
)
LINKABLE = SCALARS + ("currency",)
HEADER_LINES = 12
MAX_REFS_PER_ITEM = 60
MAX_NODES = 12_000

_AMBIGUOUS = re.compile(r"[-+]?\d{1,3}[.,]\d{3}")
_MONTHS = {
    name: number
    for number, names in enumerate((
        ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
        ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
        ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
        ("dec", "december"),
    ), start=1)
    for name in names
}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", _plain(text))


def _find(text, words, piece) -> list:
    target = _norm(text)
    if not target:
        return []
    joined, spans = "", []
    for word in words:
        part = piece[id(word)]
        spans.append((len(joined), len(joined) + len(part)))
        joined += part
    starts = {a for a, b in spans if b > a}
    ends = {b for a, b in spans if b > a}
    at = joined.find(target)
    while at >= 0 and not (at in starts and at + len(target) in ends):
        at = joined.find(target, at + 1)
    if at < 0:
        return []
    end = at + len(target)
    hits = [k for k, (a, b) in enumerate(spans) if b > a and a >= at and b <= end]
    return words[hits[0]:hits[-1] + 1]


def _search(text, lines, used, piece):
    for line in lines:
        pool = [w for w in line["words"] if id(w) not in used]
        got = _find(text, pool, piece)
        if got:
            return got, pool
    for n in range(len(lines) - 1):
        if lines[n]["page"] != lines[n + 1]["page"]:
            continue
        pool = [w for w in lines[n]["words"] + lines[n + 1]["words"] if id(w) not in used]
        got = _find(text, pool, piece)
        if got:
            return got, pool
    return [], []


def _date(value, lines, used) -> list:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(value))
    if not match:
        return []
    year, month, day = (int(part) for part in match.groups())
    orders = (("d", "m", "y"), ("m", "d", "y"), ("y", "m", "d"))
    wanted = {"d": day, "m": month, "y": year}
    for line in lines:
        free = [w for w in line["words"] if id(w) not in used]
        parts = []
        for word in free:
            text = _norm(word[0])
            digits = [int(part) for part in re.findall(r"\d+", str(word[0]))]
            if digits in ([day, month, year], [year, month, day]):
                return [word]
            if text.isdigit():
                parts.append((word, int(text), False))
            elif text in _MONTHS:
                parts.append((word, _MONTHS[text], True))
        for k in range(len(parts) - 2):
            trio = parts[k:k + 3]
            for order in orders:
                if all(
                    number == wanted[role] and (role == "m" or not named)
                    for (_, number, named), role in zip(trio, order)
                ):
                    return [word for word, _, _ in trio]
    return []


def _amount(value, lines, used) -> list:
    wanted = round(abs(float(value)), 6)
    spare = []
    for line in reversed(lines):
        for word, found in line["numbers"]:
            if wanted not in found:
                continue
            if id(word) not in used:
                return [word]
            spare = spare or [word]
    return spare


def _vote(value, text, votes) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    shown = str(text).replace(" ", "")
    if not _AMBIGUOUS.fullmatch(shown):
        return
    if abs(float(value)) == float(re.sub(r"\D", "", shown)):
        votes["thousands"] += 1
    elif abs(float(value)) == float(shown.lstrip("+-").replace(",", ".")):
        votes["decimal"] += 1


def _headers(headers, layout, boxes, lines, ids, used) -> list:
    width = len(headers)
    out = [[] for _ in range(width)]
    located, bands, page_of = layout["located"], layout["bands"], layout["page_of"]
    first = next((i for i, ok in enumerate(located) if ok and bands[i]), None)
    if first is None:
        return out
    start, page = bands[first][0], page_of[first]
    terms = [_terms(header) if isinstance(header, str) else set() for header in headers]
    centers = {
        c: statistics.median((w[1] + w[3]) / 2 for w in boxes[c])
        for c in range(width) if boxes[c]
    }
    seen = False
    for n in range(start - 1, max(start - 1 - HEADER_LINES, -1), -1):
        line = lines[n]
        if line["page"] != page:
            break
        named = [w for w in line["words"] if _terms(w[0])]
        found = []
        for word in named:
            columns = [c for c in range(width) if _terms(word[0]) & terms[c]]
            if columns and id(word) not in used:
                found.append((word, columns))
        if not named or len(found) * 2 < len(named):
            if seen:
                break
            continue
        seen = True
        for word, columns in found:
            middle = (word[1] + word[3]) / 2
            near = min(centers, key=lambda c: abs(centers[c] - middle), default=None)
            loose = [c for c in columns if c not in centers]
            if near in columns:
                chosen = near
            elif len(loose) == 1:
                chosen = loose[0]
            else:
                continue
            used.add(id(word))
            out[chosen].append(ids[id(word)])
    return [sorted(refs) for refs in out]


def _table(table, lines, ids, used, piece, votes):
    layout = _layout(table, lines)
    if layout is None:
        return None
    headers, values, cells = layout["headers"], layout["values"], layout["cells"]
    page_of, bands, located = layout["page_of"], layout["bands"], layout["located"]
    band_numbers, anchors, column_of = layout["band_numbers"], layout["anchors"], layout["column_of"]
    width = len(headers)
    rows, at = [], []
    boxes = [[] for _ in range(width)]

    def take(row, c, words):
        for word in words:
            used.add(id(word))
            row[c].append(ids[id(word)])
            boxes[c].append(word)

    for i in range(len(values)):
        row = [[] for _ in range(width)]
        here = [[] for _ in range(width)]
        rows.append(row)
        at.append(here)
        if not located[i]:
            continue
        page = page_of[i]
        mapped = [(column_of(w, page), w, found) for w, found in band_numbers[i]]
        for column, word, _ in mapped:
            if column is not None:
                here[column].append(ids[id(word)])
        wanted = []
        for c, (kind, content) in enumerate(cells[i]):
            if kind == "number":
                wanted.append((c, content))
            elif kind == "blank" and _numbers(values[i][c]) is not None:
                wanted.append((c, {0.0}))
        for anchored in (True, False):
            for c, content in wanted:
                if ((page, c) in anchors) != anchored:
                    continue
                hits = [
                    word for column, word, found in mapped
                    if found & content and id(word) not in used
                    and column == (c if anchored else None)
                ]
                if hits and (anchored or len(hits) == 1):
                    take(row, c, hits[:1])
                    _vote(values[i][c], hits[0][0], votes)
        texts = sorted(
            (c for c, (kind, _) in enumerate(cells[i]) if kind == "text"),
            key=lambda c: -len(_norm(values[i][c])),
        )
        for _ in range(2):
            for c in texts:
                if row[c]:
                    continue
                rest = [w for n in bands[i] for w in lines[n]["words"] if id(w) not in used]
                take(row, c, _find(values[i][c], rest, piece))
    return {
        "headers": _headers(headers, layout, boxes, lines, ids, used),
        "rows": rows,
        "at": at,
    }


def locate(data, pages) -> dict:
    result = {"fields": {}, "other": {}, "tables": [], "number_style": None}
    if not isinstance(data, dict):
        return result
    tables = data.get("tables") if isinstance(data.get("tables"), list) else []
    result["tables"] = [None] * len(tables)
    pages = pages if isinstance(pages, list) else []
    lines = _lines(pages)
    if not lines:
        return result
    ids = {
        id(word): [p, i]
        for p, page in enumerate(pages) if isinstance(page, dict)
        for i, word in enumerate(page.get("words") or [])
    }
    piece = {id(w): _norm(w[0]) for line in lines for w in line["words"]}
    used = set()
    votes = {"thousands": 0, "decimal": 0}

    for index, table in enumerate(tables):
        result["tables"][index] = _table(table, lines, ids, used, piece, votes)

    for name in SCALARS:
        value = data.get(name)
        if value is None or value == "" or isinstance(value, bool):
            continue
        if name == "doc_date":
            got = _date(value, lines, used)
        elif isinstance(value, (int, float)):
            got = _amount(value, lines, used)
        else:
            got, _ = _search(value, lines, used, piece)
        if got:
            used.update(id(w) for w in got)
            result["fields"][name] = [ids[id(w)] for w in got]

    other = data.get("other_fields")
    for label, value in (other.items() if isinstance(other, dict) else []):
        key, pool = _search(label, lines, used, piece)
        used.update(id(w) for w in key)
        got = []
        if isinstance(value, str) and _norm(value):
            if key:
                cut = next(k for k, w in enumerate(pool) if w is key[-1])
                got = _find(value, [w for w in pool[cut + 1:] if id(w) not in used], piece)
            if not got and len(_norm(value)) >= 3:
                got, _ = _search(value, lines, used, piece)
            used.update(id(w) for w in got)
        if key or got:
            result["other"][label] = {
                "k": [ids[id(w)] for w in key],
                "v": [ids[id(w)] for w in got],
            }

    if votes["thousands"] != votes["decimal"]:
        result["number_style"] = "thousands" if votes["thousands"] > votes["decimal"] else "decimal"
    return result


def _refs(value) -> list:
    out = []
    for item in value if isinstance(value, list) else []:
        if (
            isinstance(item, (list, tuple)) and len(item) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in item)
        ):
            out.append([item[0], item[1]])
    return out[:MAX_REFS_PER_ITEM]


def clean_sources(sources, extraction) -> dict:
    if not isinstance(sources, dict) or not isinstance(extraction, dict):
        return {}
    given = sources.get("fields")
    fields = {
        name: _refs(refs)
        for name, refs in (given.items() if isinstance(given, dict) else [])
        if name in LINKABLE and extraction.get(name) not in (None, "")
    }
    labels = extraction.get("other_fields")
    labels = labels if isinstance(labels, dict) else {}
    given = sources.get("other")
    other = {
        label: {"k": _refs(entry.get("k")), "v": _refs(entry.get("v"))}
        for label, entry in (given.items() if isinstance(given, dict) else [])
        if label in labels and isinstance(entry, dict)
    }
    given = sources.get("tables")
    given = given if isinstance(given, list) else []
    current = extraction.get("tables")
    tables = []
    for index, table in enumerate(current if isinstance(current, list) else []):
        entry = given[index] if index < len(given) else None
        cleaned = None
        if isinstance(table, dict) and isinstance(entry, dict):
            columns, rows = table.get("columns"), table.get("rows")
            headers, cells = entry.get("headers"), entry.get("rows")
            if (
                isinstance(columns, list) and isinstance(rows, list)
                and isinstance(headers, list) and isinstance(cells, list)
                and len(headers) == len(columns) and len(cells) == len(rows)
                and all(isinstance(row, list) and len(row) == len(columns) for row in cells)
            ):
                cleaned = {
                    "headers": [_refs(refs) for refs in headers],
                    "rows": [[_refs(refs) for refs in row] for row in cells],
                }
        tables.append(cleaned)
    nodes = sum(len(refs) for refs in fields.values())
    nodes += sum(len(entry["k"]) + len(entry["v"]) for entry in other.values())
    for table in tables:
        if table:
            nodes += sum(1 + len(refs) for refs in table["headers"])
            nodes += sum(1 + len(refs) for row in table["rows"] for refs in row)
    if nodes > MAX_NODES:
        return {}
    return {"fields": fields, "other": other, "tables": tables}
