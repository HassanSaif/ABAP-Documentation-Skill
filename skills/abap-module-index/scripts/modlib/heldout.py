"""
heldout.py -- held-out validation of rule R1, defined exactly once.

Rule R1 (home package) is the only authoritative attribution signal in the ladder, so
it needs independent truth. Any SAP-side export that carries a `package` / `devclass`
column per object works: an ATC run, a cloud-readiness check, SE80 download, a
custom-code register. The column is never an input to the attribution, so it is
genuinely held out.

This lives in one module because two callers quote the result -- the step that BUILDS
the map and the step that VALIDATES it -- and when they each computed it separately
they disagreed (691/691 against 688/691), because one resolved an object name to its
first package and the other to its last.

A handful of object NAMES legitimately belong to two packages under different object
types (a program in one package, a structure of the same name in another). Picking
either by file order is arbitrary, and whichever you pick you manufacture
disagreements that are not real. So the rule is: a name AGREES if any package it is
mapped to matches any package the held-out source reports for it.
"""

import collections
import csv

csv.field_size_limit(10_000_000)


def load_reference(spec):
    """object_name -> {packages} from a held-out CSV. {} when there is none.

    spec: {"csv": path, "object_column": ..., "package_column": ..., "delimiter": ","}
    """
    if not spec or not spec.get("csv"):
        return {}
    import pathlib
    path = pathlib.Path(spec["csv"])
    if not path.exists():
        return {}
    obj_col = spec.get("object_column", "object_name")
    pkg_col = spec.get("package_column", "package")
    delim = spec.get("delimiter", "\t" if path.suffix.lower() in (".tsv", ".tab")
                     else ",")
    out = collections.defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter=delim):
            obj = (row.get(obj_col) or "").strip().upper()
            pkg = (row.get(pkg_col) or "").strip().upper()
            if obj and pkg:
                out[obj].add(pkg)
    return dict(out)


def _matches(mine, ref_pkgs):
    # startswith both ways, so a parent package and its sub-package are not a conflict.
    return mine in ref_pkgs or any(mine.startswith(p) or p.startswith(mine)
                                  for p in ref_pkgs)


def agreement(name_to_packages, spec):
    """Compare the package map against the held-out source.

    name_to_packages: object_name -> set of packages the map assigns.
    Returns None when there is nothing to compare against -- which is a legitimate
    state, and must be reported as "not validated", never as a pass.
    """
    ref = load_reference(spec)
    if not ref:
        return None
    agree = disagree = unresolved = 0
    misses = []
    for obj, ref_pkgs in sorted(ref.items()):
        mine = name_to_packages.get(obj)
        if not mine:
            unresolved += 1
        elif any(_matches(m, ref_pkgs) for m in mine):
            agree += 1
        else:
            disagree += 1
            if len(misses) < 12:
                misses.append((obj, sorted(mine), sorted(ref_pkgs)))
    total = agree + disagree
    return {"agree": agree, "disagree": disagree, "total": total,
            "unresolved": unresolved,
            "rate": round(100.0 * agree / total, 2) if total else 0.0,
            "misses": misses,
            "source": str(spec.get("csv"))}


def packages_by_name(rows):
    """object_package_map.tsv rows -> object_name -> {packages}."""
    out = collections.defaultdict(set)
    for row in rows:
        out[row["object_name"]].add(row["package"])
    return dict(out)
