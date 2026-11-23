#!/usr/bin/env python3
"""
Template-compliance checker for the abap-documentation skill.

Reads every per-object doc and reports whether it follows the 11-section
template mandated by the skill — BOTH structurally (all 11 headers present)
AND content-wise (sections actually populated, on-topic, non-templated).

The 11 required top-level section headers (skill SKILL.md §"Embedded template"):

  ## 1. End-User Story
  ## 2. Functional View
  ## 3. Technical Overview
  ## 4. Detailed Technical Spec
  ## 5. Database operations
  ## 6. External calls
  ## 7. Authorization
  ## 8. Customising / Configuration dependencies
  ## 9. Quirks / observations
  ## 10. Cross-references
  ## 11. Inferences & assumptions

Failure tiers:
- "partial" — one or more of the 11 headers missing (structural failure).
- "hollow"  — all 11 headers present but content checks failed (drift failure:
  empty sections, template residue, off-topic body, or duplicated §4 bodies
  across docs — the classic parallel-sub-agent degradation signature).

Content checks (deterministic, zero-token):
  H1 empty-section: a section body < 40 meaningful chars that is not marked
     "Not applicable — <reason>".
  H2 template-residue: skeleton placeholder fragments left in the body.
  H3 off-topic: the object name (doc filename stem) absent from the doc body.
  H4 no-substance-§4: §4 has neither a line-number reference nor any ABAP
     token — a vague-filler signature.
  H5 duplicate-§4: the same normalized §4 body appears in 2+ docs of the same
     family — sub-agents emitting shared filler.
  H6 meta-filler/title-echo: a section whose text talks ABOUT the section
     instead of documenting the object ("This section is for End-User Story",
     "to be documented", or a body that only restates the section title).

Tolerances applied:
- Section header allows minor wording variations for the same numbered slot.
- README, index, and stub files (< 30 lines) are skipped as legitimately compact.
- Delta / Thin / Stub / Skip tier docs are counted as intentional non-v1.

Usage:
    python scripts/check_template_compliance.py [--repo-root .] [--json]
        [--strict] [--no-content] [--paths <doc-or-folder> ...]

    --paths limits the audit to specific files/folders (use it to gate a single
    sub-agent batch cheaply instead of re-auditing the whole repo).

Exit codes:
- 0 = zero partial AND zero hollow docs among substantive docs (100% gate in --strict).
- 1 = one or more partial/hollow docs remain (for CI use).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


# Required section headers — order matters, wording tolerant
REQUIRED_SECTIONS = [
    (1,  r"^##\s*1\.\s*End[-\s]?User\s+Story"),
    (2,  r"^##\s*2\.\s*Functional\s+View"),
    (3,  r"^##\s*3\.\s*Technical\s+Overview"),
    (4,  r"^##\s*4\.\s*Detailed\s+Technical\s+Spec"),
    (5,  r"^##\s*5\.\s*Database\s+operations"),
    (6,  r"^##\s*6\.\s*External\s+calls"),
    (7,  r"^##\s*7\.\s*Authorization|^##\s*7\.\s*Authori[sz]ation"),
    (8,  r"^##\s*8\.\s*Customi[sz]ing"),
    (9,  r"^##\s*9\.\s*Quirks"),
    (10, r"^##\s*10\.\s*Cross[-\s]?references"),
    (11, r"^##\s*11\.\s*Inferences"),
]

SECTION_SPLIT_RX = re.compile(r"^##\s*(\d{1,2})\.\s*[^\n]*$", re.MULTILINE)

NOT_APPLICABLE_RX = re.compile(r"not\s+applicable", re.IGNORECASE)

# Skeleton fragments that must never survive into a real doc (H2)
TEMPLATE_RESIDUE = [
    "<One-line purpose>",
    "<Object type>",
    "<2–4 sentences",
    "<2-4 sentences",
    "<claim that cannot be verified",
    "<trigger condition>",
    "<entity keys",
    "<documents posted",
    "<config tables read at runtime",
    "<Honest list:",
    "<docs that reference this object>",
    "{{",
    "TODO",
    "TBD",
    "lorem ipsum",
]

# Residue tokens that are legitimate when quoted as source artifacts (see H2).
# A doc reporting `TODO` comments found in the code it documents is correct;
# an unquoted TODO in the prose is unfinished documentation.
RESIDUE_QUOTABLE = {"TODO", "TBD"}

# ABAP-ish substance tokens for §4 (H4)
ABAP_TOKENS_RX = re.compile(
    r"\b(SELECT|INSERT|UPDATE|MODIFY|DELETE|CALL\s+FUNCTION|CALL\s+METHOD|"
    r"CALL\s+TRANSACTION|CONCATENATE|MESSAGE|CATCH|ENQUEUE\w*|DEQUEUE\w*|"
    r"METHOD|FORM|PERFORM|LOOP|AUTHORITY-CHECK|SUBMIT|COMMIT|ROLLBACK|"
    r"BAPI_\w+|CL_\w+|ZCL_\w+|IF_\w+|ZIF_\w+)\b|sy-\w+")
# Line citations.  Docs commonly cite `l.30` / `ll.30-42` far more often than the
# spelled-out "line 30"; recognise both, or substantive sections that cite only
# the short form are reported as having no line reference at all.
LINE_REF_RX = re.compile(r"\blines?\s+\d+|\bll?\.\s?\d+", re.IGNORECASE)

# Meta-filler phrases — text ABOUT the section instead of documentation (H6)
META_FILLER_RX = re.compile(
    r"(this\s+section\s+(is\s+for|describes|covers|contains|provides|will|"
    r"documents|outlines|explains)|"
    r"to\s+be\s+(documented|filled|completed|added|written)|"
    r"documentation\s+(pending|to\s+follow|will\s+be\s+added)|"
    r"placeholder|coming\s+soon|"
    r"as\s+per\s+the\s+template|refer\s+to\s+the\s+template|"
    r"content\s+goes\s+here|section\s+intentionally|"
    r"details?\s+(will\s+be|to\s+be)\s+(added|provided|documented))",
    re.IGNORECASE)

# Stopwords for the title-echo check
_STOP = {"the","a","an","of","for","and","or","to","in","on","is","this",
         "that","section","view","overview","operations","spec","story",
         "references","observations","assumptions","calls","dependencies"}

SECTION_TITLE_WORDS = {
    1: {"end","user","story"}, 2: {"functional","view"},
    3: {"technical","overview"}, 4: {"detailed","technical","spec"},
    5: {"database","operations"}, 6: {"external","calls"},
    7: {"authorization","authorisation"},
    8: {"customising","customizing","configuration","dependencies"},
    9: {"quirks","observations"}, 10: {"cross","references"},
    11: {"inferences","assumptions"},
}


def is_title_echo(num: int, body: str, obj_name: str) -> bool:
    """Body that only restates the section title (+ object name) is filler."""
    meaningful = _meaningful(body)
    if len(meaningful) >= 200:
        return False
    tokens = {t for t in re.findall(r"[a-z]+", meaningful.lower()) if len(t) > 1}
    tokens -= _STOP
    tokens -= SECTION_TITLE_WORDS.get(num, set())
    tokens -= {t for t in re.findall(r"[a-z]+", obj_name.lower())}
    # fewer than 4 substantive tokens left => the body said nothing
    return len(tokens) < 4

MIN_SECTION_CHARS = 40   # meaningful chars below which a section is "empty" (H1)

# Tier markers that mean "intentionally not-11-section".
# NOTE: "compact" is deliberately NOT here — a compact-generator doc that has
# been regenerated with the 11-section skeleton IS compliant (structurally),
# and must not early-exit as "intentional". Only true Delta / Thin / Stub /
# Skip / pointer / dispositional markers are legitimate reasons to skip the
# 11-section requirement.
INTENTIONAL_TIER_MARKERS = [
    "Delta",       # clone-family sibling — references canonical
    "Thin",        # SM30 / wrapper / pointer stub
    "Stub",        # source-missing (DOC-002)
    "Skip",        # index-only per rule 9
    "pointer stub",
    "Pointer stub",
    "dispositional",
    "PHASE G TRIAGE",
    "index-only",
]

# Files we don't audit
# Registers and indexes are not object docs and have no 11-section shape.
# CDS_EXTENSIONS_REGISTER.md is an example of a file explicitly labelled a register.
SKIPPED_FILENAMES = {"README.md", "MASTER_INDEX.md", "COVERAGE.md",
                     "METHODOLOGY.md", "DRILL_CHECKLIST.md", "resume.md",
                     "CDS_EXTENSIONS_REGISTER.md"}

# Families we audit + their doc folder
FAMILIES = [
    ("T-Codes",         "tcodes"),
    ("Programs",        "programs"),
    ("Classes",         "classes"),
    ("Function Groups", "function_groups"),
    ("Enhancements",    "enhancements"),
    ("CDS views",       "cds"),
    ("Adobe/Smart Forms", "forms"),
    ("SICF nodes",      "sicf"),
    ("OData services",  "odata"),
    ("AIF profiles",    "aif"),
    ("Web Dynpro/WEBI", "webdynpro"),
    ("Web services (WEBI/SOAP)", "webservices"),
    ("Interfaces",      "interfaces"),
]

MIN_LINES_TO_AUDIT = 30  # Docs shorter than this are skipped as legitimate stubs


def split_sections(text: str) -> dict[int, str]:
    """Return {section_number: body_text} for top-level `## N.` headers."""
    sections: dict[int, str] = {}
    matches = list(SECTION_SPLIT_RX.finditer(text))
    for i, m in enumerate(matches):
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if 1 <= num <= 11 and num not in sections:
            sections[num] = text[start:end]
    return sections


def _meaningful(body: str) -> str:
    """Strip markdown noise so length reflects real content."""
    body = re.sub(r"[|\-=*_#>`\s]+", " ", body)
    return body.strip()


def normalize_for_hash(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip().lower()


def content_check(path: Path, text: str) -> tuple[list[str], str]:
    """
    Run content checks H1–H4 on a structurally compliant doc.
    Returns (list_of_failure_reasons, sec4_hash_for_H5).
    """
    reasons: list[str] = []
    sections = split_sections(text)

    # H1 — empty sections
    empty = []
    for num in range(1, 12):
        body = sections.get(num, "")
        if NOT_APPLICABLE_RX.search(body):
            continue
        if len(_meaningful(body)) < MIN_SECTION_CHARS:
            empty.append(num)
    if empty:
        reasons.append("H1 empty-section(s): " + ",".join(map(str, empty)))

    # H2 — template residue.
    # Skeleton fragments ("<Object type>", "{{", ...) are never legitimate
    # anywhere in a doc, so they are matched against the raw text.
    # Bare word markers are different: a §9 punch-list that REPORTS the TODO /
    # TBD comments found in the documented source is doing exactly its job. Only
    # count those when they appear outside inline-code spans and fenced blocks,
    # i.e. as unquoted prose, which is what real documentation residue looks like.
    text_unquoted = re.sub(r"```.*?```", " ", text, flags=re.S)
    text_unquoted = re.sub(r"`[^`\n]*`", " ", text_unquoted)
    residue = [
        frag for frag in TEMPLATE_RESIDUE
        if frag in (text_unquoted if frag in RESIDUE_QUOTABLE else text)
    ]
    if residue:
        reasons.append("H2 template-residue: " + "; ".join(residue[:3]))

    # H3 — off-topic: object name must appear in the body
    stem = path.stem.upper()
    if len(stem) >= 4 and stem not in text.upper():
        reasons.append(f"H3 off-topic: object name '{stem}' absent from doc body")

    # H6 — meta-filler / title-echo: text ABOUT the section, not documentation
    meta = []
    for num in range(1, 12):
        body = sections.get(num, "")
        if not body or NOT_APPLICABLE_RX.search(body):
            continue
        m = _meaningful(body)
        if len(m) < MIN_SECTION_CHARS:
            continue  # already handled by H1
        if (META_FILLER_RX.search(body) and len(m) < 300) or \
                is_title_echo(num, body, path.stem):
            meta.append(num)
    if meta:
        reasons.append("H6 meta-filler/title-echo section(s): "
                       + ",".join(map(str, meta)))

    # H4 — §4 substance
    sec4 = sections.get(4, "")
    if sec4 and not NOT_APPLICABLE_RX.search(sec4):
        if not (ABAP_TOKENS_RX.search(sec4) or LINE_REF_RX.search(sec4)):
            reasons.append("H4 no-substance-§4: no ABAP token or line reference")

    sec4_hash = ""
    if sec4 and not NOT_APPLICABLE_RX.search(sec4) and len(_meaningful(sec4)) >= MIN_SECTION_CHARS:
        sec4_hash = hashlib.md5(normalize_for_hash(sec4).encode()).hexdigest()

    return reasons, sec4_hash


def classify_doc(path: Path, content_checks: bool = True):
    """
    Returns (tier, missing_sections, hollow_reasons, sec4_hash).

    Order of classification:
      1. too_short (< MIN_LINES_TO_AUDIT lines)
      2. If doc carries the old compact-generator footer signature
         ("v1 (compact"), classify as partial regardless of tier marker.
      3. If head-20 lines contain a legitimate intentional-tier marker → intentional.
      4. Check the 11 required section headers → partial if any missing.
      5. Content checks H1–H4 → hollow if any fail.  (H5 applied by the caller
         across the family, using sec4_hash.)
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ("unreadable", list(range(1, 12)), [], "")

    def _missing(t):
        out = []
        for num, pattern in REQUIRED_SECTIONS:
            if not re.search(pattern, t, re.MULTILINE | re.IGNORECASE):
                out.append(num)
        return out

    # Compact-generator signature — always partial regardless of length or tier marker.
    if ("v1 (compact" in text or "compact — grep-based analysis" in text
            or "compact - grep-based" in text):
        missing = _missing(text)
        if missing:
            return ("partial", missing, [], "")
        # falls through to content checks below

    lines = text.splitlines()
    if len(lines) < MIN_LINES_TO_AUDIT:
        return ("too_short", [], [], "")

    head = "\n".join(lines[:20])
    for marker in INTENTIONAL_TIER_MARKERS:
        if marker in head:
            return ("intentional", [], [], "")

    missing = _missing(text)
    if missing:
        return ("partial", missing, [], "")

    if content_checks:
        reasons, sec4_hash = content_check(path, text)
        if reasons:
            return ("hollow", [], reasons, sec4_hash)
        return ("compliant", [], [], sec4_hash)

    return ("compliant", [], [], "")


def audit_family(family_name: str, folder: Path, content_checks: bool = True,
                 only_paths: set[Path] | None = None) -> dict:
    """Audit every .md file in the family folder."""
    if not folder.exists():
        return {"family": family_name, "folder": str(folder),
                "exists": False, "counts": {}, "non_compliant_sample": [],
                "hollow_sample": []}

    counts = defaultdict(int)
    non_compliant = []
    hollow = []
    sec4_hashes: dict[str, list[str]] = defaultdict(list)
    compliant_hash_of: dict[str, str] = {}

    for path in sorted(folder.glob("*.md")):
        if path.name in SKIPPED_FILENAMES:
            counts["skipped_index"] += 1
            continue
        if only_paths is not None and path.resolve() not in only_paths:
            continue
        tier, missing, reasons, sec4_hash = classify_doc(path, content_checks)
        if sec4_hash:
            sec4_hashes[sec4_hash].append(path.name)
            if tier == "compliant":
                compliant_hash_of[path.name] = sec4_hash
        counts[tier] += 1
        if tier == "partial":
            non_compliant.append({"doc": path.name,
                                  "missing_sections": missing,
                                  "missing_count": len(missing)})
        elif tier == "hollow":
            hollow.append({"doc": path.name, "reasons": reasons})

    # H5 — duplicate §4 bodies across the family (drift signature)
    if content_checks:
        for h, names in sec4_hashes.items():
            if len(names) > 1:
                for name in names:
                    if name in compliant_hash_of:
                        counts["compliant"] -= 1
                        counts["hollow"] += 1
                        hollow.append({"doc": name, "reasons": [
                            "H5 duplicate-§4: identical body shared with "
                            + ", ".join(n for n in names if n != name)]})
                        del compliant_hash_of[name]
                    else:
                        for item in hollow:
                            if item["doc"] == name and not any(
                                    r.startswith("H5") for r in item["reasons"]):
                                item["reasons"].append(
                                    "H5 duplicate-§4: identical body shared with "
                                    + ", ".join(n for n in names if n != name))

    counts["_total_audited"] = (counts["compliant"] + counts["partial"]
                                + counts["hollow"] + counts["intentional"]
                                + counts["too_short"])

    return {
        "family": family_name,
        "folder": str(folder),
        "exists": True,
        "counts": dict(counts),
        "non_compliant_sample": sorted(non_compliant,
                                       key=lambda x: -x["missing_count"])[:20],
        "hollow_sample": hollow[:20],
    }


def render_text_report(results: list[dict]) -> str:
    """Human-readable report."""
    lines = []
    lines.append("=" * 88)
    lines.append("ABAP-DOCUMENTATION TEMPLATE-COMPLIANCE REPORT")
    lines.append("=" * 88)
    lines.append("")
    lines.append("compliant  = all 11 headers present AND content checks pass")
    lines.append("partial    = header(s) missing (structural failure)")
    lines.append("hollow     = headers present but empty/templated/off-topic/duplicated content")
    lines.append("intentional= marked Delta/Thin/Stub/Skip/pointer — legitimately non-v1")
    lines.append("")
    lines.append("-" * 88)
    lines.append(f"{'Family':<20} {'Compliant':>10} {'Partial':>9} {'Hollow':>8} "
                 f"{'Intent.':>9} {'Short':>7} {'Comply%':>9}")
    lines.append("-" * 88)

    totals = defaultdict(int)
    for r in results:
        if not r["exists"]:
            lines.append(f"{r['family']:<20} (folder missing)")
            continue
        c = r["counts"]
        compliant = c.get("compliant", 0)
        partial = c.get("partial", 0)
        hollow = c.get("hollow", 0)
        intent = c.get("intentional", 0)
        short = c.get("too_short", 0)
        substantive = compliant + partial + hollow
        pct = (compliant / substantive * 100) if substantive > 0 else 100
        lines.append(f"{r['family']:<20} {compliant:>10} {partial:>9} {hollow:>8} "
                     f"{intent:>9} {short:>7} {pct:>8.1f}%")
        totals["compliant"] += compliant
        totals["partial"] += partial
        totals["hollow"] += hollow
        totals["intent"] += intent
        totals["short"] += short

    lines.append("-" * 88)
    total_substantive = totals["compliant"] + totals["partial"] + totals["hollow"]
    total_pct = (totals["compliant"] / total_substantive * 100
                 if total_substantive > 0 else 100)
    lines.append(f"{'TOTAL':<20} {totals['compliant']:>10} {totals['partial']:>9} "
                 f"{totals['hollow']:>8} {totals['intent']:>9} {totals['short']:>7} "
                 f"{total_pct:>8.1f}%")
    lines.append("=" * 88)
    lines.append("")

    for r in results:
        if not r["exists"]:
            continue
        if r["non_compliant_sample"]:
            lines.append(f"[{r['family']}] partial docs (missing headers):")
            for item in r["non_compliant_sample"]:
                missing_str = ",".join(str(n) for n in item["missing_sections"])
                lines.append(f"  {item['doc']:<50} missing sections: {missing_str}")
            lines.append("")
        if r["hollow_sample"]:
            lines.append(f"[{r['family']}] hollow docs (content failures):")
            for item in r["hollow_sample"]:
                lines.append(f"  {item['doc']}")
                for reason in item["reasons"]:
                    lines.append(f"      - {reason}")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check per-object docs against the 11-section template "
                    "(structure + content).")
    parser.add_argument("--repo-root", default=".",
                        help="Project root (contains docs/).")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON instead of text.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if ANY partial or hollow doc exists "
                             "(100%% gate, per SKILL.md Phase 3.5).")
    parser.add_argument("--no-content", action="store_true",
                        help="Skip content checks (structural headers only).")
    parser.add_argument("--paths", nargs="*", default=None,
                        help="Limit audit to these doc files/folders "
                             "(cheap per-batch gate for sub-agent output).")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    docs_root = root / "docs"
    if not docs_root.exists():
        print(f"ERROR: docs folder not found at {docs_root}", file=sys.stderr)
        return 2

    only_paths = None
    if args.paths:
        only_paths = set()
        for p in args.paths:
            pp = Path(p).resolve()
            if pp.is_dir():
                only_paths.update(f.resolve() for f in pp.glob("*.md"))
            else:
                only_paths.add(pp)

    results = []
    for name, folder in FAMILIES:
        results.append(audit_family(name, docs_root / folder,
                                    content_checks=not args.no_content,
                                    only_paths=only_paths))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(render_text_report(results))

    if args.strict:
        bad = sum(r["counts"].get("partial", 0) + r["counts"].get("hollow", 0)
                  for r in results if r["exists"])
        if bad > 0:
            print(f"\nSTRICT: {bad} partial/hollow doc(s) remain. "
                  f"Gate requires zero.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
