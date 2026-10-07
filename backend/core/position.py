import re
import statistics
import unicodedata

MAX_ISSUES = 50
MAX_CELLS = 400_000
ROW_SCORE_MIN = 2.0
COLUMN_TOLERANCE = 1.2

_NUMBER = re.compile(r"[-+]?[\d.,]*\d[\d.,]*")
_GLUED = re.compile(r"([-+]?[\d.,]*\d[\d.,]*)[^\d.,%]")
_FEATURES = (
    lambda word: word[1],
    lambda word: (word[1] + word[3]) / 2,
    lambda word: word[3],
)


def _plain(text) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", str(text)) if unicodedata.category(c) != "Mn"
    )
    return stripped.lower().replace("đ", "d")


def _terms(text) -> set:
    return {word for word in re.split(r"[^a-z0-9]+", _plain(text)) if len(word) >= 2}


def _parse(text: str) -> set:
    values = {float(re.sub(r"\D", "", text))}
    cut = max(text.rfind("."), text.rfind(","))
    if cut >= 0:
        whole = re.sub(r"\D", "", text[:cut]) or "0"
        fraction = re.sub(r"\D", "", text[cut + 1:])
        if fraction:
            values.add(round(float(f"{whole}.{fraction}"), 6))
    return values


def _numbers(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return {round(abs(float(value)), 6)}
    text = str(value).replace(" ", "").rstrip("%")
    return _parse(text) if _NUMBER.fullmatch(text) else None


def _glued(text):
    found = _GLUED.match(str(text).replace(" ", ""))
    return _parse(found.group(1)) if found else None


def _lines(pages) -> list[dict]:
    lines = []
    for page_index, page in enumerate(pages or []):
        if not isinstance(page, dict):
            continue
        words = [w for w in (page.get("words") or []) if isinstance(w, (list, tuple)) and len(w) >= 5]
        if not words:
            continue
        height = statistics.median(w[4] - w[2] for w in words)
        groups = []
        for word in sorted(words, key=lambda w: (w[2] + w[4]) / 2):
            middle = (word[2] + word[4]) / 2
            if groups and abs(middle - groups[-1][0]) < 0.5 * height:
                groups[-1][1].append(word)
                groups[-1][0] = statistics.fmean((w[2] + w[4]) / 2 for w in groups[-1][1])
            else:
                groups.append([middle, [word]])
        parsed = [(w, _numbers(w[0])) for w in words]
        widths = [(w[3] - w[1]) / max(len(str(w[0])), 1) for w, found in parsed if found]
        char_width = statistics.median(widths) if widths else 0.007
        for _, members in groups:
            numbers = [(w, found) for w, found in ((w, _numbers(w[0])) for w in members) if found]
            lines.append({
                "page": page_index,
                "char_width": char_width,
                "words": sorted(members, key=lambda w: w[1]),
                "terms": set().union(*[_terms(w[0]) for w in members]),
                "numbers": numbers,
                "values": set().union(*[found for _, found in numbers]),
                "glued": [g for g in (_glued(w[0]) for w in members) if g],
            })
    return lines


def _cell(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return ("blank", None)
    numbers = _numbers(value)
    if numbers is None:
        return ("text", _terms(value))
    return ("blank", None) if all(n == 0 for n in numbers) else ("number", numbers)


def _score(cells, line) -> float:
    total = 0.0
    for kind, content in cells:
        if kind == "text" and content and len(content & line["terms"]) / len(content) >= 0.6:
            total += 2
        elif kind == "number" and content & line["values"]:
            total += 1 if max(content) >= 100 else 0.3
    return total


def _place(rows, lines) -> list[int]:
    count, width = len(rows), len(lines)
    worst = float("-inf")
    best = [[worst] * width for _ in rows]
    back = [[-1] * width for _ in rows]
    for index in range(width):
        best[0][index] = _score(rows[0], lines[index])
    for row in range(1, count):
        running, running_at = worst, -1
        for index in range(width):
            if index and best[row - 1][index - 1] > running:
                running, running_at = best[row - 1][index - 1], index - 1
            if running_at >= 0:
                best[row][index] = running + _score(rows[row], lines[index])
                back[row][index] = running_at
    index = max(range(width), key=lambda i: best[count - 1][i])
    placed = [0] * count
    for row in range(count - 1, -1, -1):
        placed[row] = index
        index = back[row][index]
    return placed


def _anchor(words, tolerance):
    best = None
    for feature in (2, 1, 0):
        points = [_FEATURES[feature](w) for w in words]
        position = statistics.median(points)
        agree = sum(1 for p in points if abs(p - position) <= tolerance)
        if best is None or agree > best[0]:
            best = (agree, feature, position)
    agree, feature, position = best
    return (feature, position) if agree * 2 > len(words) else None


def _layout(table, lines):
    if not isinstance(table, dict):
        return None
    columns, rows = table.get("columns"), table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or not columns or not rows:
        return None
    if any(not isinstance(c, dict) for c in columns) or any(not isinstance(r, dict) for r in rows):
        return None
    count = len(rows)
    if count > len(lines) or count * len(lines) > MAX_CELLS:
        return None

    headers = [c.get("header") for c in columns]
    values = [[row.get(header) for header in headers] for row in rows]
    cells = [[_cell(v) for v in row] for row in values]
    placed = _place(cells, lines)
    page_of = [lines[index]["page"] for index in placed]

    gaps = [placed[i + 1] - placed[i] for i in range(count - 1) if page_of[i] == page_of[i + 1]]
    reach = max(1, int(statistics.median(gaps))) if gaps else 1
    bands = []
    for i in range(count):
        stop = min(placed[i] + reach, placed[i + 1] if i + 1 < count else len(lines))
        bands.append([n for n in range(placed[i], stop) if lines[n]["page"] == page_of[i]])

    located = [_score(cells[i], lines[placed[i]]) >= ROW_SCORE_MIN for i in range(count)]
    if sum(located) * 2 < count:
        return None

    tolerance = {line["page"]: COLUMN_TOLERANCE * line["char_width"] for line in lines}
    band_numbers = [[(w, found) for n in band for w, found in lines[n]["numbers"]] for band in bands]

    samples = {}
    for i in range(count):
        if not located[i]:
            continue
        owners = {}
        for c, (kind, content) in enumerate(cells[i]):
            if kind != "number":
                continue
            hits = [k for k, (_, found) in enumerate(band_numbers[i]) if found & content]
            if len(hits) == 1:
                owners.setdefault(hits[0], []).append(c)
        for k, columns_hit in owners.items():
            if len(columns_hit) == 1:
                samples.setdefault((page_of[i], columns_hit[0]), []).append(band_numbers[i][k][0])

    anchors = {}
    for (page, c), words in samples.items():
        anchor = _anchor(words, tolerance[page])
        if anchor:
            anchors[(page, c)] = anchor

    def column_of(word, page):
        chosen, nearest = None, tolerance[page]
        for (anchor_page, c), (feature, position) in anchors.items():
            distance = abs(_FEATURES[feature](word) - position)
            if anchor_page == page and distance <= nearest:
                chosen, nearest = c, distance
        return chosen

    return {
        "headers": headers, "values": values, "cells": cells, "page_of": page_of,
        "bands": bands, "located": located, "band_numbers": band_numbers,
        "anchors": anchors, "column_of": column_of,
    }


def _check_table(table_index, table, lines) -> list[dict]:
    layout = _layout(table, lines)
    if layout is None:
        return []
    headers, values, cells = layout["headers"], layout["values"], layout["cells"]
    page_of, bands, located = layout["page_of"], layout["bands"], layout["located"]
    band_numbers, anchors, column_of = layout["band_numbers"], layout["anchors"], layout["column_of"]

    issues = []
    for i in range(len(values)):
        if not located[i]:
            continue
        page = page_of[i]
        mapped = [(column_of(w, page), w, found) for w, found in band_numbers[i]]
        glued = [g for n in bands[i] for g in lines[n]["glued"]]
        for c, (kind, content) in enumerate(cells[i]):
            if kind == "text" or (page, c) not in anchors:
                continue
            here = [(w, found) for column, w, found in mapped if column == c]
            message = None
            if kind == "blank":
                other = [str(w[0]) for w, found in here if any(n != 0 for n in found)]
                if other:
                    message = (
                        f"Kết quả để trống hoặc 0, nhưng trên chứng từ tại đúng cột này "
                        f"của dòng có {other[0]}"
                    )
            elif not any(found & content for _, found in here):
                matches = [(column, found) for column, _, found in mapped if found & content]
                spare = [
                    str(headers[column]) for column, found in matches
                    if column is not None
                    and not (cells[i][column][0] == "number" and cells[i][column][1] & found)
                ]
                if spare:
                    message = (
                        f"Giá trị {values[i][c]} nằm ở cột {' / '.join(dict.fromkeys(spare))} "
                        f"trên chứng từ, không phải cột này"
                    )
                elif matches and all(column is not None for column, _ in matches):
                    message = f"Không thấy giá trị {values[i][c]} tại cột này trên chứng từ"
                elif not matches and not any(g & content for g in glued):
                    message = f"Không thấy giá trị {values[i][c]} trên dòng này của chứng từ"
            if message:
                issues.append({
                    "field": f"tables.{table_index}.rows.{i}.{headers[c]}",
                    "table": table_index,
                    "row": i,
                    "column": headers[c],
                    "col": c,
                    "value": values[i][c],
                    "message": message,
                })
    return issues


def check_positions(data, pages) -> list[dict]:
    if not isinstance(data, dict):
        return []
    tables = data.get("tables")
    if not isinstance(tables, list) or not tables:
        return []
    lines = _lines(pages if isinstance(pages, list) else [])
    if not lines:
        return []
    issues = []
    for index, table in enumerate(tables):
        issues.extend(_check_table(index, table, lines))
    return issues[:MAX_ISSUES]


def still_valid(issues, extraction) -> list[dict]:
    tables = extraction.get("tables") if isinstance(extraction, dict) else None
    kept = []
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        try:
            table = tables[issue["table"]]
            column = issue["column"]
            if isinstance(issue.get("col"), int):
                column = table["columns"][issue["col"]]["header"]
            current = table["rows"][issue["row"]].get(column)
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        if current != issue.get("value"):
            continue
        if column != issue["column"]:
            issue = {
                **issue,
                "column": column,
                "field": f"tables.{issue['table']}.rows.{issue['row']}.{column}",
            }
        kept.append(issue)
    return kept
