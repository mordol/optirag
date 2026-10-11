"""Stage 4-1: notes/chunking_spec.md 규칙대로 output/*.json → chunks.jsonl"""
import glob, html, json, os, re, unicodedata
from transformers import AutoTokenizer

try:
    import yaml
except ImportError:  # exclude_rules.yaml이 있으면 pyyaml 필요 (requirements.txt 참조)
    yaml = None

MAX_TOK, MIN_TOK, OVERLAP_MAX = 512, 50, 128
tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")
ntok = lambda s: len(tok(s, add_special_tokens=False)["input_ids"])
TOC_RE = re.compile(r"\S\s\d{1,3}(?=\s|$)")
FIG_RE = re.compile(r"(Figure|Fig\.|Table|그림|표)\s*\d", re.I)
BULLET_RE = re.compile(r"^\s*([●○•▪◦\-–]|https?://)")
SENT_END_RE = re.compile(r"(다|요|[.?!:])\s*$")


EXCLUDE_RULES, _excluded = [], 0
_excl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclude_rules.yaml")
if os.path.exists(_excl_path):
    if yaml is None:
        raise SystemExit("exclude_rules.yaml이 있지만 pyyaml이 없습니다: pip install pyyaml (형식은 exclude_rules.example.yaml 참조)")
    _cfg = yaml.safe_load(open(_excl_path, encoding="utf-8")) or {}
    EXCLUDE_RULES = [re.compile(r["pattern"], re.I | re.M) for r in _cfg.get("rules", [])]  # MULTILINE: ^$가 줄 단위 매칭
    print(f"exclude rules: {len(EXCLUDE_RULES)} loaded", flush=True)


def below_ratio(n, ref):
    """ref(표/이미지) 아래 n까지의 세로 간격 ÷ n의 높이. 같은 페이지가 아니면 None"""
    if ref is None or ref["type"] not in ("table", "image"):
        return None
    page, box = ref.get("_page_end", ref["page number"]), ref.get("_last_bbox", ref["bounding box"])  # 병합된 표는 마지막 조각 기준
    if page != n["page number"]:
        return None
    h = max(n["bounding box"][3] - n["bounding box"][1], 1)
    return (box[1] - n["bounding box"][3]) / h


def is_caption(n, prev=None):
    """캡션 판정 (spec §3-5). 글꼴 정보는 쓰지 않음:
    caption 타입 / 'Figure·Table·그림·표 N'으로 시작 / 표·이미지 바로 아래(간격 ≤ 자기 높이의 0.5)에 붙은 짧은 비문장"""
    if n["type"] == "caption":
        return True
    if n["type"] not in ("paragraph", "heading", "list item"):
        return False
    t = text_of(n)
    if not t or ntok(t) > 60 or BULLET_RE.match(t):
        return False
    if FIG_RE.match(t):
        return True
    r = below_ratio(n, prev)
    return r is not None and -0.5 <= r <= 0.5 and not SENT_END_RE.search(t)


def level_of(n, prev=None, front=False):
    """섹션 경계 heading이면 파서의 heading level, 아니면 None (spec §2). 글꼴 크기는 쓰지 않음.
    front=True(첫 본문 섹션 이전)일 때만 '텍스트 숫자' 형태를 목차 항목으로 보고 제외"""
    if n["type"] != "heading":
        return None
    t = text_of(n)
    if not t or len(t) > 150 or front and re.search(r"\s\d{1,3}$", t) or BULLET_RE.match(t) or is_caption(n, prev):
        return None
    return n.get("heading level") or 2


def text_of(n):
    if n["type"] == "list":
        return "\n".join(text_of(li) for li in n["list items"])
    s = n.get("content") or ""
    for k in n.get("kids") or []:
        s += " " + text_of(k)
    return html.unescape(s.replace("\x00", "").strip())


def apply_exclusions(n):
    """boilerplate 문장 제외 (exclude_rules.yaml). 매칭된 부분만 re.sub로 제거하고,
    요소의 남은 텍스트가 비면 그 요소를 제외. 목록은 항목별로 적용. 표/heading/캡션/이미지는 건드리지 않음.
    텍스트 패턴 기준이라 글꼴 정보는 사용하지 않음 (spec v3 §2 준수).
    매칭 전 NFKC 정규화로 합자(ﬁ→fi) 등을 ASCII 패턴과 매칭. 매칭이 없는 요소는 원문 그대로 둠."""
    global _excluded
    if not EXCLUDE_RULES or n["type"] not in ("paragraph", "list item", "list"):
        return n
    if n["type"] == "list":
        items = [li for li in map(apply_exclusions, n["list items"]) if li is not None]
        return dict(n, **{"list items": items}) if items else None
    t = norm = unicodedata.normalize("NFKC", text_of(n))
    for rx in EXCLUDE_RULES:
        t = rx.sub("", t)
    if t == norm:
        return n
    t = re.sub(r"\n{2,}", "\n", re.sub(r"[ \t]+", " ", t)).strip()
    if t:
        return dict(n, content=html.escape(t, quote=False), kids=[])  # text_of가 다시 unescape하므로 escape해 둠
    _excluded += 1
    return None


def table_rows(t):
    rows = []
    for r in t["rows"]:
        cells = [""] * t["number of columns"]
        for c in r["cells"]:
            cells[c["column number"] - 1] = " ".join(text_of(k) for k in c.get("kids") or [])
        rows.append("|" + "|".join(cells) + "|")
    return rows


def render_table(rows):
    ncol = rows[0].count("|") - 1
    return "\n".join([rows[0], "|" + "---|" * ncol] + rows[1:])


def relocate_list_captions(kids):
    """spec §6-4: 파서가 list로 묶은 캡션 항목을 꺼내 같은 페이지에서 바로 위 요소 뒤에 재배치"""
    out, caps = [], []
    for n in kids:
        if n["type"] == "list":
            items = n["list items"]
            refs = [r for r in kids if r["type"] in ("table", "image") and r["page number"] == n["page number"]]
            cap = [li for li in items if FIG_RE.match(text_of(li)) or any(is_caption(li, r) for r in refs)]
            if cap:
                caps += [dict(li, type="caption") for li in cap]
                rest = [li for li in items if li not in cap]
                if not rest:
                    continue
                n = dict(n, **{"list items": rest})
        out.append(n)
    for c in caps:
        top = c["bounding box"][3]
        above = [(n["bounding box"][1] - top, i) for i, n in enumerate(out)
                 if n["page number"] == c["page number"] and n["bounding box"][1] >= top - 3]
        out.insert(min(above)[1] + 1 if above else len(out), c)
    return out


def merge_split_tables(kids):
    """spec §6-1: 다음 페이지로 이어지는 같은 열 수의 표를 앞 표에 합침"""
    out = []
    for n in kids:
        if n["type"] == "table":
            prev = next((p for p in reversed(out) if p["type"] not in ("image", "caption")), None)
            if (prev is not None and prev["type"] == "table"
                    and n["page number"] == prev["_page_end"] + 1
                    and n["number of columns"] == prev["number of columns"]):
                prev["_rows"] += table_rows(n)
                prev["_page_end"] = n["page number"]
                prev["_last_bbox"] = n["bounding box"]
                continue
            n = dict(n, _rows=table_rows(n), _page_end=n["page number"])
        out.append(n)
    return out


def crumb_of(title, path):
    """breadcrumb. 구성요소는 60자에서 자름 (spec §3-3)"""
    cut = lambda t: t if len(t) <= 60 else t[:59] + "…"
    return f"[{cut(title)}] " + " > ".join(cut(p) for p in path)


def units_of(n, limit):
    """요소 → 패킹 단위 [(text, page, bbox, is_table, table_id)]. limit(=512 - breadcrumb) 초과 요소는 미리 분할 (spec §4)"""
    page, bbox = n["page number"], n["bounding box"]
    if n["type"] == "table":
        head, body = n["_rows"][0], n["_rows"][1:]
        groups, cur = [], []
        for r in body:
            if cur and ntok(render_table([head] + cur + [r])) > limit - 60:  # 캡션 반복 여유분
                groups.append(cur); cur = []
            cur.append(r)
        groups.append(cur)
        return [(render_table([head] + g), page, bbox, True, n["id"]) for g in groups]
    text = text_of(n)
    if not text:
        return []
    if ntok(text) <= limit:
        return [(text, page, bbox, False, None)]
    seps = r"(?<=\n)" if n["type"] == "list" else r"(?<=다\.)\s+|(?<=\.)\s+|\n"
    parts, cur = [], ""
    for s in re.split(seps, text):
        if cur and ntok(cur + " " + s) > limit:
            parts.append(cur); cur = ""
        cur = (cur + " " + s).strip()
    parts.append(cur)
    return [(p, page, bbox, False, None) for p in parts]


def sections_of(doc):
    kids = merge_split_tables(relocate_list_captions(doc["kids"]))
    title = next((text_of(n) for n in kids if n["type"] == "heading" and n.get("heading level") == 1),
                 doc["file name"])
    path, secs, cur = {}, [], None
    seen_sec, prev = False, None
    for n in kids:
        lv = level_of(n, prev, front=not seen_sec)
        if lv:
            if lv > 1:
                seen_sec = True
                path = {k: v for k, v in path.items() if k < lv}
                path[lv] = text_of(n)
            cur = {"path": [path[k] for k in sorted(path)], "top": path[min(path)] if path else None, "units": []}
            cur["limit"] = MAX_TOK - ntok(crumb_of(title, cur["path"])) - 2
            secs.append(cur)
            prev = n
            continue
        cap = is_caption(n, prev)
        prev = n
        if n["type"] == "image" or cur is None:
            continue
        if not seen_sec and len(TOC_RE.findall(text_of(n))) >= 2:  # 목차 (spec §3-4)
            continue
        n = apply_exclusions(n)  # exclude_rules.yaml boilerplate 제거
        if n is None:
            continue
        us = cur["units"]
        if cap and us and ntok(us[-1][0]) + ntok(text_of(n)) <= cur["limit"]:
            # 캡션은 직전 단위에 붙여 다음 청크 앞으로 넘어가지 않게 함.
            # 직전 단위가 분할된 표의 조각이면 같은 표의 모든 조각에 반복 (spec §3-5)
            tid = us[-1][4]
            for j in range(len(us)):
                if j == len(us) - 1 or (tid is not None and us[j][4] == tid):
                    t, pg, bb, tb, k = us[j]
                    us[j] = (t + "\n" + text_of(n), pg, bb, tb, k)
            continue
        us += units_of(n, cur["limit"])
    secs = [s for s in secs if s["units"]]  # 본문 없는 heading은 breadcrumb로만 (spec §3-2)
    # 50토큰 미만 섹션은 같은 최상위 섹션 안의 다음(없으면 이전) 섹션과 합침 (spec §4)
    i = 0
    while i < len(secs):
        s = secs[i]
        if sum(ntok(u[0]) for u in s["units"]) < MIN_TOK and len(secs) > 1:
            label = ("#### " + s["path"][-1], s["units"][0][1], s["units"][0][2], False, None) if s["path"] else None
            moved = ([label] if label else []) + s["units"]
            if i + 1 < len(secs) and secs[i + 1]["top"] == s["top"]:
                secs[i + 1]["units"] = moved + secs[i + 1]["units"]; secs.pop(i); continue
            if i > 0 and secs[i - 1]["top"] == s["top"]:
                secs[i - 1]["units"] += moved; secs.pop(i); continue
        i += 1
    return title, secs


def chunks_of(path):
    doc = json.load(open(path))
    title, secs = sections_of(doc)
    for s in secs:
        crumb = crumb_of(title, s["path"])
        budget = MAX_TOK - ntok(crumb) - 2
        groups, cur, size = [], [], 0
        for u in s["units"]:
            t = ntok(u[0])
            if cur and size + t > budget:
                groups.append(cur)
                last = cur[-1]  # 섹션 내부 분할 시 마지막 단락 1개 오버랩 (spec §5)
                cur = [last] if not last[3] and ntok(last[0]) <= OVERLAP_MAX and ntok(last[0]) + t <= budget else []
                size = sum(ntok(x[0]) for x in cur)
            cur.append(u); size += t
        groups.append(cur)
        # 분할 후 50토큰 미만 조각은 앞(없으면 뒤) 청크에 병합 (spec §4)
        size_of = lambda g: sum(ntok(u[0]) for u in g)
        i = 0
        while len(groups) > 1 and i < len(groups):
            if size_of(groups[i]) < MIN_TOK:
                if i > 0 and size_of(groups[i - 1]) + size_of(groups[i]) <= budget:
                    groups[i - 1] += [u for u in groups.pop(i) if u not in groups[i - 1]]; continue
                if i + 1 < len(groups) and size_of(groups[i]) + size_of(groups[i + 1]) <= budget:
                    groups[i + 1] = [u for u in groups.pop(i) if u not in groups[i]] + groups[i]; continue
            i += 1
        for g in groups:
            page = g[0][1]
            boxes = [u[2] for u in g if u[1] == page]
            yield {
                "file": doc["file name"], "page": page, "page_end": max(u[1] for u in g),
                "section": " > ".join(s["path"]),
                "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)],
                "has_table": any(u[3] for u in g),
                "text": crumb + "\n" + "\n\n".join(u[0] for u in g),
            }


if __name__ == "__main__":
    # usage: python chunk.py [JSON_DIR=output/] [OUT=chunks.jsonl]
    import sys
    json_dir = sys.argv[1] if len(sys.argv) > 1 else "output/"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "chunks.jsonl"
    n = 0
    with open(out_path, "w") as f:
        for p in sorted(glob.glob(os.path.join(json_dir, "*.json"))):
            stem = os.path.basename(p)[:-5]
            for i, c in enumerate(chunks_of(p)):
                c = {"chunk_id": f"{stem}::{i:04d}", **c}
                f.write(json.dumps(c, ensure_ascii=False) + "\n"); n += 1
    print("chunks", n, "| excluded elements:", _excluded)
