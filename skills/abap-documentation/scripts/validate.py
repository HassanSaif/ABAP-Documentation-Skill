#!/usr/bin/env python3
"""
abap-documentation Coverage & Link Validator — Phase 4 of the methodology.

Reads `docs/_index/raw/*.tsv` plus the actual `docs/<area>/*.md` files and reports:

  1. Coverage per family — which TSV rows have per-object docs, which don't.
  2. Orphan docs — `.md` files in `docs/<area>/` with no corresponding TSV row.
  3. Broken markdown links — every relative link in every `docs/**/*.md`
     is resolved against the filesystem.
  4. Hidden-alias coverage — for SICF, every node with an ICFALTNME alias
     should ideally have a per-object stub even if not bespoke.

No third-party dependencies. Runs against the standard layout produced by
the `extract.py` harness and the methodology's `docs/<area>/` folder convention.

Usage:
    python validate.py [--repo-root .] [--index docs/_index/raw] [--docs docs] [--strict]
                       [--sicf-handler-namespace /XYZ/ ...]

Exit code:
    0 always, unless --strict and any issues found.
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional


# Family -> (logical-name column, target docs folder, optional filter)
# Where "filter" decides whether a TSV row is "in scope" for per-object docs.
# Returning False = out-of-scope (no doc expected, won't be flagged as gap).
# Fallback key column, used when a family's primary key column is empty on an
# in-scope row (see the note in coverage_report). Without this, such rows are
# counted nowhere.
NAME_FALLBACK = {"sicf.tsv": "icf_name"}

# Partner / add-on namespaces whose SICF handler classes count as bespoke,
# e.g. /DBE/ and /DBME/ for the DBE Automotive Service Solution. Repo-specific,
# so empty by default -- extend with --sicf-handler-namespace (repeatable).
SICF_HANDLER_NAMESPACES: list[str] = []

FAMILY_MAP = [
    # SICF: Z-namespace + bespoke handler nodes are in scope; DS41* standard
    # auto-activations without an ICFALTNME alias are out of scope.
    #
    # Do NOT test handler.startswith("ZCL_"). Many repos name handler classes
    # ZXX_<mod>_CL_REST_HANDLER -- "CL" MID-NAME, not a prefix -- and a prefix
    # test reports most custom REST handler nodes out of scope. Any
    # Z-namespace handler qualifies (same rule as the classes family).
    #
    # Deliberately still OUT of scope, as a stated judgement rather than an
    # accident: nodes on SAP's own handlers such as CL_HTTP_EXT_ITS (an ITS
    # service publishing an RF dynpro over HTTP). The handler is SAP's; the
    # service is custom. If such a node should be documented, widen this rule
    # deliberately rather than by loosening the handler test.
    ("sicf.tsv", "icf_altnme", "sicf", lambda row:
        (row.get("icf_altnme") or "").startswith("Z")
        or (row.get("handler") or "").upper().startswith("Z")
        or (row.get("handler") or "").upper().startswith(tuple(SICF_HANDLER_NAMESPACES))
    ),
    # OData: every Z-prefixed service is substantive.
    ("iwsv.tsv", "external_name", "odata", lambda row:
        (row.get("external_name") or "").upper().startswith("Z")
    ),
    # Enhancements: every Z-prefixed impl is substantive.
    # TWO source families. A migrated classic BAdI is serialized twice -- once
    # as *.sxci.xml and once as *.enho.xml -- and THE TWO NAMES OFTEN DIFFER:
    # e.g. ENHO ZXX_ORDER_UPDATE_CHECK carries MIG_BADI_IMPL = ZXX_ORDER_RELEASE.
    # So the union is deduplicated on the ENHO's mig_badi_impl column, not on
    # the name. Handled specially below, outside the generic in_scope filter,
    # because it needs rows from one TSV to filter rows of another.
    #
    # Without sxci.tsv, an SXCI-only implementation (real code, no ENHO twin)
    # is invisible to coverage and any doc written for it is reported as an
    # orphan forever. Listing sxci.tsv as a SECOND FAMILY_MAP entry would not
    # work: each entry compares against the whole docs/ folder, so the two
    # passes would each report the other family's docs as orphans.
    ("enho.tsv", "enh_name", "enhancements", lambda row:
        (row.get("enh_name") or "").upper().startswith("Z")
    ),
    # Classes: skip auto-gen DPC/MPC and non-custom classes.
    # NB: match the whole custom namespace, not just the ZCL_/ZCX_ prefix forms.
    # Many repos put the CL token in the middle (ZXX_PP_CL_FASTENTRY,
    # ZABC_CL_EDOCUMENT_GR) or use other prefixes (ZXX_*, Z*_CX_*); a
    # prefix-only test silently drops those from coverage and then reports any
    # doc written for them as an orphan.
    # Generated proxy classes (Z*_CO_*, "Proxy Class (generated)") stay in scope
    # here — mark them index-only in the area index per methodology rule 9.
    ("clas.tsv", "clsname", "classes", lambda row:
        (row.get("clsname") or "").upper().startswith(("Z", "Y"))
        and not row.get("is_dpc_mpc")
    ),
    # Function groups: every Z-prefixed FG is at least candidate.
    ("fugr.tsv", "fugr_name", "function_groups", lambda row:
        (row.get("fugr_name") or "").upper().startswith("Z")
    ),
    # Programs: executable Z programs (SUBC=1) AND module pools (SUBC=M).
    # Module pools are dialog-transaction targets and are drilled like any
    # other program; they routinely carry live T-Codes. Scoping to SUBC=1 alone
    # makes every one of them both unreportable as a gap AND an orphan once
    # documented.
    ("prog.tsv", "progname", "programs", lambda row:
        (row.get("progname") or "").upper().startswith("Z")
        and (row.get("subc") or "") in ("1", "M", "S", "I")
        # SUBC = 'I' (include) is in scope so that drilled includes -- e.g.
        # SAP customer function-exit includes (ZX*), which reach straight into
        # SD/MM/FI -- have somewhere to be filed instead of being orphans.
        # Do NOT model includes as a second FAMILY_MAP entry on incl.tsv
        # pointing at docs/programs/: two families over one folder make each
        # pass report the other's docs as orphans. Widening the subc set keeps
        # it to one family and one pass.
        # This adds many gaps, which costs nothing -- gaps are informational by
        # design, ORPHANS are the signal -- and it does NOT commit the
        # programme to documenting every include.
        # SUBC = 'S' (subroutine pool) is in scope too. A pool is called rather
        # than run, but Z pools are often the SHARED CODE OF THE PRINT LAYER --
        # the top targets of SAPscript / form PERFORM ... IN PROGRAM calls.
        # Excluding them makes a doc for such a pool an orphan forever.
        # Any "substantive programs" figure in docs/_methodology.md must state
        # which SUBC values it counts, or it will disagree with this scope.
    ),
    # CDS: load-bearing Z views — names starting Z usually.
    # Adobe / Smart Forms are HOST objects: the layout carries binding and visibility
    # logic no driver program states, and one form is often shared by several drivers,
    # so it cannot be folded into any one of them. Without this family a form doc has
    # nowhere correct to live and is reported as an orphan forever.
    ("sfpf.tsv", "form_name", "forms", lambda row:
        (row.get("form_name") or "").upper().startswith(("Z", "Y"))
    ),
    ("ddls.tsv", "view_name", "cds", lambda row:
        (row.get("view_name") or "").upper().startswith("Z")
    ),
    # T-Codes: every Z* T-Code in scope -- AND the Y namespace.
    # Y-namespace transactions are customer objects like any other; scoping
    # to Z alone is an assumption about naming, not about substance, and it
    # makes a doc written for a Y transaction an orphan while hiding the
    # object from coverage.
    ("tran.tsv", "tcode", "tcodes", lambda row:
        (row.get("tcode") or "").upper().startswith(("Z", "Y"))
    ),
]


def _read_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


FAMILY_MARKER = "<!-- family-doc:"


def _list_md(docs_dir: Path, area: str) -> set[str]:
    """Doc stems in an area, EXCLUDING self-declared family/surface docs.

    Some docs legitimately describe a family, a package or a cross-cutting
    surface rather than one repository object -- e.g. `cds/ZXX_DS.md` (every
    view in one package), `odata/WEBI_SOAP_SURFACE.md` (many published
    services as one surface). Their stems are not object names, so they would
    be reported as orphans forever, which would destroy the "orphans must be
    0" signal.

    A doc opts out by carrying `<!-- family-doc: <reason> -->` in its first 30
    lines. The marker is IN the file rather than in an allowlist here, so it
    travels with the doc, states its own reason, and cannot silently exempt a
    doc nobody meant to exempt.
    """
    folder = docs_dir / area
    if not folder.exists():
        return set()
    out = set()
    for p in folder.glob("*.md"):
        if p.name.upper() == "README.MD":
            continue
        try:
            head = "".join(p.open(encoding="utf-8").readlines()[:30])
        except OSError:
            head = ""
        if FAMILY_MARKER in head:
            continue
        out.add(p.stem.upper())
    return out


def coverage_report(index_dir: Path, docs_dir: Path) -> tuple[int, int]:
    """Returns (n_gaps, n_orphans)."""
    print("=" * 78)
    print("COVERAGE REPORT")
    print("=" * 78)
    total_gaps = 0
    total_orphans = 0
    for tsv_name, name_col, area, in_scope in FAMILY_MAP:
        tsv = _read_tsv(index_dir / tsv_name)
        if not tsv:
            print(chr(10) + "[" + tsv_name + "] (no rows - skipped)")
            continue
        # Do NOT filter on `r.get(name_col)`: that silently DROPS any in-scope
        # row whose key column is empty -- and because out_of_scope counts
        # `not in_scope(r)`, such a row is not counted on that side either. It
        # vanishes from both halves of the ledger while the numbers still look
        # self-consistent. Custom SICF handler nodes typically have an empty
        # ICFALTNME, so they would pass the scope test and still be invisible.
        # A row with no usable name falls back to a per-family alternative
        # column instead.
        def _row_name(r):
            v = (r.get(name_col) or "").strip()
            if not v:
                v = (r.get(NAME_FALLBACK.get(tsv_name, "")) or "").strip()
            return v.upper()

        in_scope_names = {n for n in (_row_name(r) for r in tsv if in_scope(r)) if n}
        out_of_scope = sum(1 for r in tsv if not in_scope(r))

        # OData: fold in the RAP service bindings. iwsv.tsv records only the
        # SEGW/Gateway V2 registrations. A RAP binding is registered through
        # *.srvb.xml -- V2 bindings additionally get .iwsv/.iwmo/.iwvb rows,
        # but V4 bindings are registered through a *.g4ba service group and
        # appear in NO iwsv row at all. So without this fold-in every OData V4
        # service in the estate is invisible to coverage and every doc written
        # for one is an orphan forever -- the same failure the sxci and cmod
        # fold-ins below were added to fix. The binding is the host object: it
        # is what decides the protocol version and which authorization object
        # guards the door (V2 -> S_SERVICE, V4 -> S_START), and one service
        # definition can carry two bindings with different answers.
        if tsv_name == "iwsv.tsv":
            srvb = _read_tsv(index_dir / "srvb.tsv")
            if srvb:
                srvb_names = {
                    (r.get("srvb_name") or "").upper() for r in srvb
                    if (r.get("srvb_name") or "").upper().startswith(("Z", "Y"))
                }
                srvb_names.discard("")
                if srvb_names:
                    in_scope_names |= srvb_names
                    tsv_name += " + srvb.tsv"

        # Enhancements: fold in the classic-BAdI family, minus the migrated
        # twins the ENHO rows already account for (see FAMILY_MAP note).
        if tsv_name == "enho.tsv":
            sxci = _read_tsv(index_dir / "sxci.tsv")
            if sxci:
                migrated = {(r.get("mig_badi_impl") or "").upper() for r in tsv}
                migrated.discard("")
                sxci_only = {
                    (r.get("sxci_name") or "").upper() for r in sxci
                    if (r.get("sxci_name") or "").upper().startswith("Z")
                    and (r.get("sxci_name") or "").upper() not in migrated
                }
                in_scope_names |= sxci_only
                tsv_name = "enho.tsv + sxci.tsv"
            # ...and the CMOD projects. A CMOD project is a host object in its own
            # right -- it is what ACTIVATES an SMOD enhancement, and a project that
            # is inactive means its exit code never runs, which no other family
            # records. Without this fold-in every cmod doc is an orphan forever,
            # exactly as sxci docs were before that family was added.
            enhc = _read_tsv(index_dir / "enhc.tsv")
            if enhc:
                enhc_names = {
                    (r.get("enhc_name") or "").upper() for r in enhc
                    if (r.get("enhc_name") or "").upper().startswith(("Z", "Y"))
                }
                enhc_names.discard("")
                if enhc_names:
                    in_scope_names |= enhc_names
                    tsv_name += " + enhc.tsv"
            cmod = _read_tsv(index_dir / "cmod.tsv")
            if cmod:
                cmod_names = {
                    (r.get("cmod_name") or "").upper() for r in cmod
                    if (r.get("cmod_name") or "").upper().startswith(("Z", "Y"))
                }
                cmod_names.discard("")
                if cmod_names:
                    in_scope_names |= cmod_names
                    tsv_name += " + cmod.tsv"
        docs = _list_md(docs_dir, area)
        documented = in_scope_names & docs
        gaps = in_scope_names - docs
        orphans = docs - in_scope_names
        print(f"\n[{tsv_name}] -> docs/{area}/")
        print(f"  in scope: {len(in_scope_names)}  documented: {len(documented)}  gaps: {len(gaps)}  out-of-scope: {out_of_scope}  orphan docs: {len(orphans)}")
        if gaps:
            print(f"  gaps ({min(len(gaps), 15)} of {len(gaps)}):")
            for g in sorted(gaps)[:15]:
                print(f"    - {g}")
            if len(gaps) > 15:
                print(f"    ... and {len(gaps) - 15} more")
            total_gaps += len(gaps)
        if orphans:
            print(f"  orphan docs:")
            for o in sorted(orphans)[:10]:
                print(f"    ? docs/{area}/{o}.md exists but no TSV row")
            total_orphans += len(orphans)
    return total_gaps, total_orphans


_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")


def _resolve_link(md_path: Path, target: str, repo_root: Path) -> Optional[Path]:
    # Strip URL fragment and query
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target:
        return None
    if target.startswith(("http://", "https://", "mailto:")):
        return None
    if target.startswith("/"):
        return (repo_root / target.lstrip("/")).resolve()
    return (md_path.parent / target).resolve()


def link_check(repo_root: Path, docs_dir: Path) -> int:
    print("\n" + "=" * 78)
    print("LINK CHECK")
    print("=" * 78)
    broken = []
    n_links = 0
    for md in docs_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _LINK_RE.finditer(text):
            target = m.group(2)
            resolved = _resolve_link(md, target, repo_root)
            if resolved is None:
                continue
            n_links += 1
            if not resolved.exists():
                broken.append((md.relative_to(repo_root), target, resolved))
    print(f"  Checked {n_links} relative links across {sum(1 for _ in docs_dir.rglob('*.md'))} markdown files.")
    if broken:
        print(f"  BROKEN ({len(broken)}):")
        for src, tgt, resolved in broken[:40]:
            print(f"    {src}  ->  {tgt}")
        if len(broken) > 40:
            print(f"    ... and {len(broken) - 40} more")
    else:
        print("  All relative links resolve.")
    return len(broken)


def compliance_check(docs_dir: Path) -> tuple[int, int]:
    """Run the template-compliance check. Returns (partial_count, compliant_count)."""
    try:
        # Import from the sibling script
        sys.path.insert(0, str(Path(__file__).parent))
        from check_template_compliance import classify_doc, FAMILIES, SKIPPED_FILENAMES  # type: ignore
    except ImportError:
        print("\n  [compliance] check_template_compliance.py not found — skipping compliance check.", file=sys.stderr)
        return 0, 0

    print("\n" + "=" * 78)
    print("TEMPLATE COMPLIANCE CHECK (11-section)")
    print("=" * 78)

    partial_total = 0
    compliant_total = 0
    for name, folder_name in FAMILIES:
        folder = docs_dir / folder_name
        if not folder.exists():
            continue
        partial_docs = []
        compliant = 0
        for path in sorted(folder.glob("*.md")):
            if path.name in SKIPPED_FILENAMES:
                continue
            # classify_doc returns (tier, missing_sections, hollow_reasons, sec4_hash)
            tier = classify_doc(path)[0]
            # 'hollow' is a compliance failure too: all 11 headers present but the
            # bodies are empty / templated / off-topic / duplicated. Counting only
            # 'partial' would let drifted docs pass this gate.
            if tier in ("partial", "hollow"):
                partial_docs.append(f"{path.name} [{tier}]")
            elif tier == "compliant":
                compliant += 1
        partial_total += len(partial_docs)
        compliant_total += compliant
        if partial_docs:
            print(f"  [{name}] {len(partial_docs)} partial-tier docs (11-section incomplete):")
            for d in partial_docs[:10]:
                print(f"    ! docs/{folder_name}/{d}")
            if len(partial_docs) > 10:
                print(f"    ... and {len(partial_docs) - 10} more")

    if partial_total == 0:
        print("  All substantive docs pass 11-section compliance.")
    else:
        print(f"\n  TOTAL partial-tier docs: {partial_total}  (compliant: {compliant_total})")
        print(f"  Dispatch the compliance reviewer per {Path(__file__).resolve().parent.parent / 'reviewer_agent_prompt.md'}")
    return partial_total, compliant_total


def main() -> int:
    ap = argparse.ArgumentParser(description="abap-documentation coverage & link + compliance validator.")
    ap.add_argument("--repo-root", default=".", help="Repo root.")
    ap.add_argument("--index", default="docs/_index/raw", help="TSV directory (relative to repo-root).")
    ap.add_argument("--docs", default="docs", help="Docs directory (relative to repo-root).")
    ap.add_argument("--strict", action="store_true",
                    help="Exit non-zero on any gap / orphan / broken link / partial-tier doc.")
    ap.add_argument("--skip-compliance", action="store_true",
                    help="Skip the 11-section template compliance check.")
    ap.add_argument("--sicf-handler-namespace", action="append", default=[], metavar="NS",
                    help="Extra namespace whose SICF handler classes are in scope, e.g. DBE for /DBE/. Repeatable.")
    args = ap.parse_args()
    # Normalise to /NS/. Accepts "DBE" or "/DBE/"; keeping only the last path
    # segment also undoes Git Bash on Windows rewriting "/DBE/" into
    # "C:/Program Files/Git/DBE/".
    SICF_HANDLER_NAMESPACES.extend(
        "/" + ns.replace("\\", "/").strip("/").split("/")[-1].upper() + "/"
        for ns in args.sicf_handler_namespace
    )

    repo_root = Path(args.repo_root).resolve()
    index_dir = (repo_root / args.index).resolve()
    docs_dir = (repo_root / args.docs).resolve()

    if not index_dir.exists():
        print(f"ERROR: index dir not found: {index_dir}", file=sys.stderr)
        print("  Run extract.py first to generate the TSVs.", file=sys.stderr)
        return 2
    if not docs_dir.exists():
        print(f"ERROR: docs dir not found: {docs_dir}", file=sys.stderr)
        return 2

    gaps, orphans = coverage_report(index_dir, docs_dir)
    broken = link_check(repo_root, docs_dir)
    partial = 0
    if not args.skip_compliance:
        partial, _ = compliance_check(docs_dir)

    print("\n" + "=" * 78)
    print(f"SUMMARY: {gaps} gaps  |  {orphans} orphan docs  |  {broken} broken links  |  {partial} partial-tier docs")
    print("=" * 78)

    if args.strict and (gaps or orphans or broken or partial):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
