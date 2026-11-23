"""
layout.py -- work out how THIS repository is serialised, without being told.

Four layouts occur in practice, and the package map -- rule R1, the only
authoritative attribution signal -- comes from a different place in each:

  A  flat export          <root>/src/*.prog.abap                (no folders at all)
                          package: from per-package .zip exports, if any exist
  B  package-per-folder    <root>/<PKG>/src/...                  (one abapGit repo per
                          package, checked out side by side)
                          package: the folder above src/
  C  abapGit repo          <root>/src/<subpkg>/...  + .abapgit.xml
                          package: subfolder names, read with FOLDER_LOGIC
  D  monorepo of repos     <root>/<anything>/<PKG>/src/...
                          package: as B, one level deeper

abapGit strips <DEVCLASS> from every object file, so an object never states its own
package. A flat export (layout A) therefore has NO package information in the tree at
all -- which is why zips matter, and why rule R1 simply does not fire without them.
Saying so is part of the deliverable; guessing is not.
"""

import collections
import json
import pathlib
import re
import zipfile

STAMP = re.compile(r"_\d{8}(?:_\d{6})?$")
OBJECT_FILE = re.compile(r"^[^.]+\.([a-z0-9]{3,5})\.")
SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__", ".idea", ".vscode",
             "docs", "utilities", "venv", ".venv"}


def _is_object_file(name, known_types):
    m = OBJECT_FILE.match(name)
    return bool(m) and m.group(1) in known_types


def _count_objects(directory, known_types, limit=400):
    n = 0
    try:
        for entry in directory.iterdir():
            if entry.is_file() and _is_object_file(entry.name, known_types):
                n += 1
                if n >= limit:
                    break
    except OSError:
        return 0
    return n


def find_object_dirs(root, known_types, max_depth=4):
    """Directories holding abapGit object files, with their object counts."""
    found = {}
    root = pathlib.Path(root)

    def walk(d, depth):
        if depth > max_depth:
            return
        try:
            children = [c for c in d.iterdir() if c.is_dir()
                        and c.name not in SKIP_DIRS and not c.name.startswith(".")]
        except OSError:
            return
        n = _count_objects(d, known_types)
        if n:
            found[d] = n
        for c in children:
            walk(c, depth + 1)

    walk(root, 0)
    return found


def read_folder_logic(repo_dir):
    """FOLDER_LOGIC + STARTING_FOLDER from .abapgit.xml, if present."""
    f = repo_dir / ".abapgit.xml"
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8-sig", errors="replace")

    def tag(t):
        m = re.search(rf"<{t}>([^<]*)</{t}>", text)
        return (m.group(1).strip() if m else "")

    return {"folder_logic": (tag("FOLDER_LOGIC") or "PREFIX").upper(),
            "starting_folder": tag("STARTING_FOLDER") or "/src/",
            "master_language": tag("MASTER_LANGUAGE")}


def package_name_of_dir(d):
    """Does this directory name look like an SAP package?"""
    n = d.name.upper()
    return n if (n.startswith(("Z", "Y", "$")) or n == "$TMP") else None


def classify(root, known_types):
    """Detect the layout. Returns a dict describing what was found."""
    root = pathlib.Path(root).resolve()
    obj_dirs = find_object_dirs(root, known_types)
    src_dirs = {d: n for d, n in obj_dirs.items() if d.name.lower() == "src"}

    repos = []          # (repo_dir, src_dir, package_or_None, folder_logic)
    for src in sorted(src_dirs):
        repo = src.parent
        repos.append({
            "repo": repo, "src": src, "objects": src_dirs[src],
            "package": package_name_of_dir(repo),
            "abapgit": read_folder_logic(repo),
            "subfolders": sorted(c.name for c in src.iterdir()
                                 if c.is_dir() and _count_objects(c, known_types)),
        })

    layout = "unknown"
    if len(repos) == 1:
        r = repos[0]
        layout = "abapgit-repo" if r["subfolders"] else "flat-export"
    elif len(repos) > 1:
        named = [r for r in repos if r["package"]]
        layout = "package-per-folder" if len(named) >= len(repos) / 2 else "multi-repo"
    elif obj_dirs:
        layout = "loose"       # object files but not under any src/

    return {"root": root, "layout": layout, "repos": repos,
            "other_object_dirs": {d: n for d, n in obj_dirs.items()
                                  if d.name.lower() != "src"}}


# --- package zips ---------------------------------------------------------------------
def package_of_zip(stem, strip_prefixes=()):
    name = STAMP.sub("", stem)
    for pfx in strip_prefixes:
        if name.upper().startswith(pfx.upper()):
            name = name[len(pfx):]
            break
    return name.upper()


def find_package_zips(root, known_types, max_depth=2):
    """Zips that look like per-package abapGit exports, with what they contain."""
    root = pathlib.Path(root).resolve()
    out = collections.defaultdict(list)

    def walk(d, depth):
        if depth > max_depth:
            return
        try:
            entries = list(d.iterdir())
        except OSError:
            return
        for e in entries:
            if e.is_dir() and e.name not in SKIP_DIRS and not e.name.startswith("."):
                walk(e, depth + 1)
            elif e.is_file() and e.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(e) as zf:
                        names = zf.namelist()
                except (zipfile.BadZipFile, OSError):
                    continue
                objs = sum(1 for n in names
                           if _is_object_file(n.rsplit("/", 1)[-1], known_types))
                if objs:
                    out[d].append({"zip": e, "objects": objs, "entries": len(names)})

    walk(root, 0)
    return dict(out)


def guess_strip_prefixes(zip_infos):
    """A common leading token on every zip name is a project label, not a package.

    'ACME_ZFOO_SD.zip' + 'ACME_ZFOO_FI.zip' -> strip 'ACME_'.
    """
    stems = [STAMP.sub("", z["zip"].stem).upper() for z in zip_infos]
    cands = collections.Counter(s.split("_", 1)[0] + "_" for s in stems if "_" in s)
    out = []
    for pfx, n in cands.most_common(3):
        core = pfx.rstrip("_")
        if n >= 2 and not core.startswith(("Z", "Y", "$")):
            out.append(pfx)
    return out


# --- held-out validation source -------------------------------------------------------
NAME_COLS = ("object_name", "objectname", "obj_name", "object", "name")
PKG_COLS = ("package", "devclass", "dev_class", "paket")


def find_heldout_candidates(root, max_depth=3, max_files=400):
    """CSV/TSV files that carry both an object-name and a package column.

    A SAP ATC or ZCC_CLOUD_READINESS export is the ideal held-out truth for rule R1,
    because its `package` column is never an input to the attribution.
    """
    import csv
    root = pathlib.Path(root).resolve()
    hits, seen = [], 0

    def probe(path):
        try:
            with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
                head = fh.readline()
        except OSError:
            return None
        delim = "\t" if path.suffix.lower() in (".tsv", ".tab") else \
            (";" if head.count(";") > head.count(",") else ",")
        cols = [c.strip().strip('"').lower()
                for c in next(csv.reader([head], delimiter=delim), [])]
        name_col = next((c for c in cols if c in NAME_COLS), None)
        pkg_col = next((c for c in cols if c in PKG_COLS), None)
        if name_col and pkg_col:
            return {"csv": path, "object_column": name_col, "package_column": pkg_col,
                    "delimiter": delim}
        return None

    def walk(d, depth):
        nonlocal seen
        if depth > max_depth or seen > max_files:
            return
        try:
            entries = list(d.iterdir())
        except OSError:
            return
        for e in entries:
            if e.is_dir() and e.name not in SKIP_DIRS and not e.name.startswith("."):
                walk(e, depth + 1)
            elif e.is_file() and e.suffix.lower() in (".csv", ".tsv", ".tab"):
                seen += 1
                got = probe(e)
                if got:
                    hits.append(got)

    walk(root, 0)
    return hits


# --- package descriptions (a strong hint for the package -> module map) ---------------
def package_descriptions(repos):
    """package -> CTEXT from package.devc.xml.

    abapGit's devc serialiser keeps only <CTEXT>, the package short text -- and that
    text is usually the most honest statement of intent in the whole estate
    ('TG Development Package for QM'). It is the best raw material for proposing the
    package -> module map.
    """
    out = {}
    for r in repos:
        src = r["src"]
        base = r["package"] or ""
        for devc in sorted(src.rglob("package.devc.xml")):
            rel = devc.parent.relative_to(src)
            if rel == pathlib.Path("."):
                pkg = base
            else:
                folder = "_".join(p.upper() for p in rel.parts)
                logic = ((r.get("abapgit") or {}).get("folder_logic") or "PREFIX")
                pkg = folder if (logic == "FULL" or folder.startswith(("Z", "Y", "$"))) \
                    else f"{base}_{folder}"
            if not pkg:
                continue
            text = devc.read_text(encoding="utf-8-sig", errors="replace")
            m = re.search(r"<CTEXT>([^<]*)</CTEXT>", text)
            if m and m.group(1).strip():
                out[pkg.upper()] = _unescape(m.group(1).strip())
    return out


def _unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            .replace("&quot;", '"').replace("&apos;", "'"))


def describe(det, zips, heldout):
    """Human-readable detection report."""
    L = [f"layout: {det['layout']}", f"root:   {det['root']}"]
    for r in det["repos"]:
        ag = r["abapgit"]
        bits = [f"{r['objects']}+ object files"]
        if r["package"]:
            bits.append(f"package {r['package']}")
        if ag:
            bits.append(f"FOLDER_LOGIC={ag['folder_logic']}")
        if r["subfolders"]:
            bits.append(f"{len(r['subfolders'])} sub-package folders")
        L.append(f"  src: {r['src']}  ({', '.join(bits)})")
    for d, infos in zips.items():
        L.append(f"  package zips: {d}  ({len(infos)} zips, "
                 f"{sum(i['objects'] for i in infos)} object entries)")
    for h in heldout:
        L.append(f"  held-out candidate: {h['csv']}  "
                 f"({h['object_column']} / {h['package_column']})")
    return "\n".join(L)


def to_json(det):
    return json.dumps({
        "layout": det["layout"],
        "root": str(det["root"]),
        "repos": [{"src": str(r["src"]), "package": r["package"],
                   "objects": r["objects"], "subfolders": r["subfolders"],
                   "abapgit": r["abapgit"]} for r in det["repos"]],
    }, indent=2)
