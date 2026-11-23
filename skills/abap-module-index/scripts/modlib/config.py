"""
config.py -- site configuration merged over the universal SAP knowledge base.

Two files, two lifetimes:

  defaults/sap-knowledge.json   ships with the skill. True of any SAP system.
                                Standard tables, BAdI spots, exit includes, object
                                types, role labels. Never edited per customer.

  module-index.config.json      lives in the target repo. Everything site-specific:
                                which modules are in scope, the package -> module map,
                                the naming conventions of THIS estate, local-language
                                keywords, third-party exclusions, tuning and thresholds.

Merge rule, applied per key:
  * dict values  -- site entries override defaults key by key (add or replace one key,
                    keep the rest)
  * list values  -- site entries are APPENDED to the defaults, because the defaults are
                    knowledge you almost never want to lose. To replace instead, wrap
                    the value: {"replace": true, "values": [...]}
  * scalars      -- site value wins

Nothing in this module reads the repository. It only resolves what to read.
"""

import json
import pathlib
import re
import sys

CONFIG_NAME = "module-index.config.json"
SCHEMA = "abap-module-index/1"

_HERE = pathlib.Path(__file__).resolve().parent
DEFAULTS_PATH = _HERE.parent / "defaults" / "sap-knowledge.json"


class ConfigError(Exception):
    pass


# --- merge ----------------------------------------------------------------------------
def _is_replace_wrapper(v):
    return isinstance(v, dict) and set(v) <= {"replace", "values"} and "values" in v


def merge(base, over):
    """Deep merge `over` onto `base` using the rule documented above."""
    if _is_replace_wrapper(over):
        return json.loads(json.dumps(over["values"]))
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list):
        out = list(base)
        for item in over:
            if item not in out:
                out.append(item)
        return out
    return over


# --- config object --------------------------------------------------------------------
DEFAULT_TUNING = {
    # BFS depth when folding a nesting into a unit. 6 is deep enough for
    # T-Code -> program -> include -> FM -> class -> helper and stops runaway chains.
    "max_hops": 6,
    # A member this many objects point at is shared plumbing, not business meaning:
    # it contributes a note, never a module tick.
    "fanin_gate": 40,
    # Name/table evidence decays with distance: hop 1 full strength, hop 2 weak,
    # deeper is evidence only.
    "tick_max_hop": 2,
    # A member's home package is an authoritative fact about that member at any depth,
    # so package evidence reaches one hop further than name evidence.
    "pkg_max_hop": 3,
    # If closure-derived rules alone reach this many core modules, the unit is marked
    # cross-module rather than ticking half the estate.
    "breadth_cap": 4,
    # Deep content evidence: this many distinct tables of ONE module, corroborated by
    # an agreeing standard call, is highly accurate against held-out truth -- enough to
    # bypass the authority floor. Below it, read evidence only reinforces.
    # Above this, "it does nothing" stops being a credible reading of an object with
    # no tables, no calls and no forms. Deliberately small: the point is to name dead
    # stubs, not to excuse anything the ladder failed on.
    "stub_max_loc": 20,
    "content_deep_tables": 5,
    "content_deep_needs_call": True,
}

DEFAULT_THRESHOLDS = {
    "min_ticked_pct": 97.0,
    "max_unclassified_pct": 3.0,
    "multi_module_band": [10.0, 30.0],
    "max_core_breadth": 5,
    "min_single_core_pct": 50.0,
    "min_high_confidence_pct": 80.0,
    "max_module_share_pct": 35.0,
    "min_heldout_pkg_pct": 98.0,
    "min_heldout_module_pct": 97.0,
    # Independent cross-check: where a NAME rule and CONTENT (standard tables touched)
    # both fire on a unit, they should mostly agree -- healthy estates sit well above
    # this floor. Below it, a naming rule has drifted from what the code does.
    "min_content_name_agreement_pct": 80.0,
    # Per-OBJECT coverage, as opposed to per-unit. Lower than min_ticked_pct on
    # purpose: units are entry points and every one of them should be attributable,
    # while objects include DDIC leaves that reach a module only through whatever uses
    # them, and an estate is entitled to a handful of genuinely unreferenced ones.
    "min_object_ticked_pct": 95.0,
}


# A regex holding a literal control character never matches, and nothing complains.
# It is the perfect silent failure, and JSON makes it easy: the two-character escape
# for backspace is backslash-b, so a word boundary written the obvious way in a config
# pattern decodes to chr(8) while the file on disk looks innocent. It must be written
# with a DOUBLED backslash. Whole sets of config family patterns have been dead this
# way, and so were regexes in this skill's own scanner -- custom-table detection from
# SELECT/INSERT/DELETE, and outbound CALL FUNCTION ... DESTINATION. The only symptom
# was evidence quietly missing from rows nobody had a reason to doubt.
_CONTROL_CHARS = re.compile(
    "[" + "".join(chr(c) for c in list(range(0, 9)) + [11, 12]
                  + list(range(14, 32))) + "]")


def check_no_control_chars(pattern, where):
    m = _CONTROL_CHARS.search(pattern or "")
    if m:
        raise ConfigError(
            f"{where}: pattern contains a literal control character "
            f"(0x{ord(m.group()):02x}) at position {m.start()}, so it can never "
            f"match. In JSON a regex word boundary must be written with a doubled "
            f"backslash. Pattern: {pattern!r}")


class Config:
    def __init__(self, root, data, knowledge, path=None):
        self.root = pathlib.Path(root).resolve()
        self.data = data
        self.k = knowledge
        self.path = path

        p = data.get("paths", {})
        self.source_roots = [self._abs(x) for x in p.get("source_roots", ["src"])]
        self.work_dir = self._abs(p.get("work_dir", "utilities/module-index"))
        self.out_dir = self._abs(p.get("out_dir", p.get("work_dir",
                                                        "utilities/module-index")))
        self.out_prefix = p.get("out_prefix", "appendix-module-index")
        self.mirrors = [self._abs(x) for x in p.get("mirrors", [])]

        self.project = data.get("project", self.root.name)
        self.seed = int(data.get("seed", 20260101))

        # --- module vocabulary --------------------------------------------------------
        # The vocabulary is OPEN. `all_modules` is what gets a tick column in the
        # deliverable; anything the rules can name beyond that is not discarded, it is
        # recorded as a PROPOSED module with its evidence (see discover.py). A module
        # only leaves the estate silently if a human puts it in modules.not_modules.
        mods = knowledge.get("modules", {})
        self.core = list(data.get("modules", {}).get("core", mods.get("core", [])))
        buckets = data.get("modules", {}).get("buckets", {})
        self.buckets = list(buckets)
        self.bucket_meta = buckets
        self.all_modules = self.core + self.buckets
        self.open_vocabulary = bool(data.get("modules", {}).get("open", True))
        # Areas a human has looked at and ruled out. Silences the proposal, on the
        # record, with a reason -- the only sanctioned way to make a signal disappear.
        nm = data.get("modules", {}).get("not_modules", {})
        self.not_modules = {k.upper(): (v or "declared not a module")
                            for k, v in (nm.items() if isinstance(nm, dict)
                                         else {x: "" for x in nm}.items())}
        # An optional bucket for "this object is an external API surface". When set,
        # an RFC-enabled function group ticks it as a fact from metadata (rule R11).
        self.integration_bucket = data.get("modules", {}).get("integration_bucket")
        # Universal SAP knowledge sometimes lands on a concern that is not an SAP
        # module -- an IDoc segment is integration, a logon exit is Basis. Knowledge
        # entries name those with the tokens '@INTEGRATION' and '@TECHNICAL' so the
        # skill never has to invent a bucket name for a customer. A token with no
        # bucket configured makes the rule not fire; it never falls back to a core
        # module it cannot justify.
        self.technical_bucket = data.get("modules", {}).get("technical_bucket")
        self._special = {"@INTEGRATION": self.integration_bucket,
                         "@TECHNICAL": self.technical_bucket}
        self.labels = dict(mods.get("labels", {}))
        for name, meta in buckets.items():
            self.labels[name] = (meta or {}).get("description", name)
        self.short_headers = {n: (m or {}).get("label", n) for n, m in buckets.items()}
        if not self.all_modules:
            raise ConfigError("no modules configured: set modules.core and/or "
                              "modules.buckets")

        # --- packages -----------------------------------------------------------------
        pk = data.get("packages", {})
        self.package_providers = pk.get("providers", [])
        self.package_strip_prefixes = [s.upper() for s in pk.get("strip_prefixes", [])]
        self.package_modules = {kk.upper(): vv for kk, vv in pk.get("map", {}).items()}
        self.excluded_packages = {s.upper() for s in pk.get("excluded", [])} | {
            s.upper() for s in knowledge.get("third_party", {}).get("packages", [])}

        # --- naming -------------------------------------------------------------------
        # Site naming is MERGED over the knowledge base, not read instead of it: the
        # site's blacklist entries and families are appended to the defaults, while
        # token_map/module_segments override per key. Reading only one of the two
        # sources silently drops whichever half is not read.
        nk = merge(knowledge.get("naming", {}), data.get("naming", {}))
        self.custom_prefixes = tuple(nk.get("custom_prefixes", ["Z", "Y"]))
        # Objects a human declares to be plumbing. The fan-in gate finds most of them
        # automatically, but it fires at an absolute in-degree, and an estate's central
        # utility can sit just under that line while still being called from everywhere
        # -- a general-purpose RFC API called from dozens of units is infrastructure by
        # any reading, and its tables smear into every caller. Listed objects contribute no name, table or field evidence; they still
        # appear as members and still get their own row.
        self.infrastructure_objects = tuple(
            n.upper() for n in nk.get("infrastructure_objects", []))
        self.module_segments = list(nk.get("module_segments", [1, 2]))
        # Not filtered to the vocabulary: a token naming an unconfigured module is a
        # discovery, not noise.
        self.token_map = {kk.upper(): vv.upper()
                          for kk, vv in nk.get("token_map", {}).items()}
        self.segment_blacklist = {s.upper() for s in nk.get("segment_blacklist", [])}
        self.type_segment_blacklist = {kk.upper(): {s.upper() for s in vv}
                                       for kk, vv in
                                       nk.get("type_segment_blacklist", {}).items()}
        self.families = []
        for f in nk.get("families", []):
            check_no_control_chars(f.get("pattern"),
                                   f"naming.families {f.get('label', '?')!r}")
            try:
                rx = re.compile(f["pattern"], re.I)
            except (KeyError, re.error) as exc:
                raise ConfigError(f"bad naming.families entry {f!r}: {exc}") from exc
            mods = [m.upper() for m in f.get("modules", [])]
            if mods:
                self.families.append((rx, mods, f.get("label", f["pattern"])))

        # --- text ---------------------------------------------------------------------
        tk = data.get("text", {})
        self.secondary_script = self._script_regex(tk.get("secondary_script"))
        self.text_keywords = {m.upper(): list(v) for m, v in
                              merge(knowledge.get("text_keywords", {}),
                                    tk.get("keywords", {})).items()}

        # --- third party --------------------------------------------------------------
        tp = merge(knowledge.get("third_party", {}), data.get("third_party", {}))
        self.excluded_packages |= {s.upper() for s in tp.get("packages", [])}
        pats = tp.get("name_patterns", [])
        self.third_party_rx = re.compile("|".join(f"(?:{p})" for p in pats), re.I) \
            if pats else None

        # --- knowledge ----------------------------------------------------------------
        # Deliberately NOT filtered to the configured vocabulary. A rule that names an
        # unconfigured module still fires; attribute.py routes the hit to the proposal
        # register instead of a tick column. That is what keeps the vocabulary open:
        # narrowing modules.core hides a column, it never hides the evidence.
        self.std_tables = {m.upper(): v for m, v
                           in knowledge.get("std_tables", {}).items()}
        nond = {t.upper() for t in knowledge.get("non_discriminating_tables", [])}
        self.non_discriminating_tables = nond
        self.table_to_module = {t.upper(): m for m, ts in self.std_tables.items()
                                for t in ts if t.upper() not in nond}
        # Every standard table the knowledge base knows, discriminating or not. A write
        # to MARA cannot attribute a module, but it is still a write to a standard SAP
        # table and the deliverable should say so.
        self.all_std_tables = ({t.upper() for ts in self.std_tables.values()
                                for t in ts} | nond)
        # Name-based resolution (R13/R14) must see the non-discriminating tables too.
        # The demotion of LFA1 or MARA is a statement about READS -- every module reads
        # vendor and material master all day -- and says nothing about a structure
        # NAMED after one, where the name is the whole point: 'ZE1LFA1M' is the vendor
        # master IDoc segment, not an incidental lookup.
        self.table_to_module_all = {t.upper(): m for m, ts in self.std_tables.items()
                                    for t in ts}
        self.std_call_prefixes = [(p.upper(), m.upper()) for p, m in
                                  knowledge.get("std_call_prefixes", [])]
        self.std_object_prefixes = [(p.upper(), m.upper()) for p, m in
                                    knowledge.get("std_object_prefixes", [])]
        self.container_types = {t.upper() for t in
                                knowledge.get("container_types", [])}
        self.presentation_types = {t.upper() for t in
                                   knowledge.get("presentation_types", [])}
        self.definitional_edges = {e.upper() for e in
                                   knowledge.get("definitional_edges", [])}
        nond_de = {e.upper() for e in
                   knowledge.get("non_discriminating_data_elements", [])}
        self.non_discriminating_data_elements = nond_de
        self.std_data_elements = sorted(
            ((e.upper(), m.upper()) for e, m
             in knowledge.get("std_data_elements", [])
             if e.upper() not in nond_de),
            key=lambda em: len(em[0]), reverse=True)
        self.composition_edges = {e.upper() for e in
                                  knowledge.get("composition_edges", [])}
        it = dict(knowledge.get("infotype_naming", {}) or {})
        if it:
            it["prefixes"] = sorted((p.upper() for p in it.get("prefixes", [])),
                                    key=len, reverse=True)
            it["module"] = self.resolve_special(it.get("module", ""))
        self.infotype_naming = it if it.get("module") else {}
        idn = dict(knowledge.get("idoc_naming", {}) or {})
        if idn:
            idn["segment_prefixes"] = [p.upper() for p in
                                       idn.get("segment_prefixes", [])]
            idn["types"] = [t.upper() for t in idn.get("types", [])]
        self.idoc_naming = idn
        self.idoc_message_types = {
            k.upper(): [m for m in (self.resolve_special(x) for x in v) if m]
            for k, v in knowledge.get("idoc_message_types", {}).items()}
        self.append_text_patterns = [re.compile(p) for p in
                                     knowledge.get("append_text_patterns", [])]
        self.fugr_include_suffixes = sorted(
            (x.upper() for x in knowledge.get("fugr_include_suffixes", [])),
            key=len, reverse=True)
        self.std_call_ignore = tuple(s.upper() for s in
                                     knowledge.get("std_call_ignore", []))
        self.badi_spots = {kk.upper(): [m.upper() for m in vv]
                           for kk, vv in knowledge.get("badi_spots", {}).items()}
        self.exit_include_prefixes = [
            (p.upper(), [m for m in (self.resolve_special(x) for x in mm) if m])
            for p, mm in knowledge.get("exit_include_prefixes", [])]
        self.exit_include_prefixes = [(p, mm) for p, mm
                                      in self.exit_include_prefixes if mm]
        self.appl_modules = {kk: vv.upper() for kk, vv in
                             knowledge.get("appl_modules", {}).items()}
        # R9: custom names that wrap a standard SAP transaction/program name.
        # The module may be a string or a LIST. A standard transaction often belongs
        # to one module and reads another's data, and both facts are worth a tick:
        # IH09 is a Plant Maintenance transaction -- that is why it can branch to
        # maintenance orders and notifications -- and what it displays is the material
        # master. First entry in the list is the owner and ranks first for
        # primary_module; the rest have a stake. Naming only the owner loses the data,
        # and naming only the data loses the process.
        self.std_name_wrappers = []
        for pat, mod in knowledge.get("std_name_wrappers", []):
            check_no_control_chars(pat, "std_name_wrappers")
            mods = [mod] if isinstance(mod, str) else list(mod)
            # resolve_special, or an '@INTEGRATION' token reaches the proposal register
            # as a module literally called "@INTEGRATION". An entry whose every module
            # is a token the site has no bucket for drops out entirely, which is the
            # intended behaviour -- never a fallback to a core module.
            mods = [m for m in (self.resolve_special(m) for m in mods) if m]
            if not mods:
                continue
            try:
                self.std_name_wrappers.append(
                    (re.compile(pat, re.I), [m.upper() for m in mods]))
            except re.error as exc:
                raise ConfigError(f"bad std_name_wrappers pattern {pat!r}: "
                                  f"{exc}") from exc
        self.generated_name_patterns = [
            re.compile(x, re.I) for x in knowledge.get("generated_name_patterns", [])]
        self.std_name_ignore = tuple(sorted(
            (n.upper() for n in knowledge.get("std_name_ignore", [])),
            key=len, reverse=True))
        self.external_comm = [(m.upper(), lab) for m, lab
                              in knowledge.get("external_comm_markers", [])]
        self.entry_edges = [e.upper() for e in knowledge.get(
            "entry_edges", ["TCODE_PGM", "PARAM_REPORT"])]

        # Every module name any rule table can produce -- the open half of the
        # vocabulary. Used by the discovery report to know what it might have missed.
        self.nameable_modules = sorted(
            {m for _rx, ms in self.std_name_wrappers for m in ms}
            | set(self.token_map.values()) | set(self.std_tables)
            | {m for _p, m in self.std_call_prefixes}
            | {m for mm in self.badi_spots.values() for m in mm}
            | {m for _p, mm in self.exit_include_prefixes for m in mm}
            | set(self.appl_modules.values()) | set(self.text_keywords)
            | {m for _rx, mm, _l in self.families for m in mm}
            )

        ot = knowledge.get("object_types", {})
        self.known_types = {t.lower() for t in ot.get("known", [])}
        self.opaque_types = {t.lower() for t in ot.get("opaque_names", [])}
        self.demote_types = {t.upper() for t in ot.get("demote", [])}
        self.role_by_type = dict(ot.get("roles", {}))
        self.enho_roles = dict(ot.get("enho_roles", {}))
        self.role_order = list(ot.get("role_order", []))
        self.root_types = [t.upper() for t in ot.get("root_types", [])]
        self.type_priority = [t.upper() for t in ot.get("type_priority", [])]
        self.unreferenced_deliverables = {t.upper() for t in
                                          ot.get("unreferenced_deliverables", [])}
        self.fold_edges = {e.upper() for e in knowledge.get("fold_edges", [])}
        self.evidence_mute_edges = {e.upper() for e in
                                    knowledge.get("evidence_mute_edges", [])}
        self.anchor_edges = tuple(e.upper() for e in knowledge.get("anchor_edges", []))

        # --- tuning and validation ----------------------------------------------------
        self.tuning = dict(DEFAULT_TUNING, **data.get("tuning", {}))
        v = data.get("validation", {})
        self.thresholds = dict(DEFAULT_THRESHOLDS, **v.get("thresholds", {}))
        self.held_out = v.get("held_out") or {}
        self.assertions = v.get("assertions", [])
        self.reviewer_default = data.get("reviewer", "")

    # --- helpers ----------------------------------------------------------------------
    def is_generated_name(self, name):
        """True for a machine-generated name that carries no business meaning."""
        n = (name or "").upper()
        return any(rx.match(n) for rx in self.generated_name_patterns)

    def is_infrastructure(self, name, fanin=0):
        n = (name or "").upper()
        if fanin and fanin >= self.tuning["fanin_gate"]:
            return True
        return any(n == p or n.startswith(p) for p in self.infrastructure_objects)

    def resolve_special(self, module):
        """'@INTEGRATION'/'@TECHNICAL' -> the site's bucket, or '' if it has none."""
        m = (module or "").upper()
        if m.startswith("@"):
            return self._special.get(m) or ""
        return m

    def in_vocab(self, module):
        """Does this module get a tick column? Everything else becomes a proposal."""
        return module in self.all_modules

    def is_ruled_out(self, module):
        return module.upper() in self.not_modules

    def _abs(self, rel):
        p = pathlib.Path(rel)
        return (p if p.is_absolute() else self.root / p).resolve()

    def _script_regex(self, name):
        if not name:
            return None
        rng = self.k.get("scripts", {}).get(name)
        if rng is None:
            # allow a raw character class
            rng = name
        try:
            return re.compile(f"[{rng}]")
        except re.error as exc:
            raise ConfigError(f"text.secondary_script {name!r} is not a known preset "
                              f"or a valid character range: {exc}") from exc

    def work(self, name):
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return self.work_dir / name

    def out(self, suffix):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir / f"{self.out_prefix}{suffix}"

    def is_third_party_name(self, name):
        return bool(self.third_party_rx and self.third_party_rx.match(name or ""))

    def rel(self, path):
        try:
            return str(pathlib.Path(path).resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def summary(self):
        return {
            "project": self.project,
            "config": str(self.path) if self.path else "(defaults only)",
            "source_roots": [self.rel(p) for p in self.source_roots],
            "work_dir": self.rel(self.work_dir),
            "out_dir": self.rel(self.out_dir),
            "core": self.core,
            "buckets": self.buckets,
            "open_vocabulary": self.open_vocabulary,
            "ruled_out": sorted(self.not_modules),
            "packages_mapped": len(self.package_modules),
            "package_providers": [p.get("type") for p in self.package_providers],
            "families": len(self.families),
            "held_out": bool(self.held_out.get("csv")),
        }


# --- loading --------------------------------------------------------------------------
def load_knowledge():
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


def find_config(start):
    """Nearest module-index.config.json at or above `start`."""
    p = pathlib.Path(start).resolve()
    for cand in [p, *p.parents]:
        f = cand / CONFIG_NAME
        if f.is_file():
            return f
    return None


def load(config_path=None, root=None):
    """Load a Config. `config_path` wins; otherwise search upwards from root/cwd."""
    knowledge = load_knowledge()
    path = pathlib.Path(config_path).resolve() if config_path else \
        find_config(root or pathlib.Path.cwd())
    if path is None:
        raise ConfigError(
            f"no {CONFIG_NAME} found. Run `modindex.py init` in the repository root "
            "to create one from what is actually in the tree.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    schema = data.get("$schema", SCHEMA)
    if schema != SCHEMA:
        print(f"WARNING: {path} declares $schema {schema!r}, this build expects "
              f"{SCHEMA!r}", file=sys.stderr)
    knowledge = merge(knowledge, data.get("knowledge", {}))
    return Config(root or path.parent, data, knowledge, path)


def validate_data(data, knowledge):
    """Cheap sanity checks on a config dict. Returns a list of problem strings."""
    problems = []
    mods = data.get("modules", {})
    core = mods.get("core") or knowledge.get("modules", {}).get("core", [])
    buckets = mods.get("buckets", {})
    vocab = set(core) | set(buckets)
    if not vocab:
        problems.append("modules.core is empty and no buckets defined")
    for name in buckets:
        if not name.startswith("X_"):
            problems.append(f"bucket {name!r} should be named X_* to keep it visibly "
                            "distinct from an SAP core module")
    # Modules named outside the vocabulary are advisory, not errors: with an open
    # vocabulary they become proposals rather than being dropped.
    for pkg, ms in (data.get("packages", {}).get("map") or {}).items():
        if isinstance(ms, str):
            problems.append(f"packages.map[{pkg}] must be a list, got a string")
            continue
        for m in ms:
            if m not in vocab:
                problems.append(f"NOTE packages.map[{pkg}] names {m!r}, which has no "
                                "tick column -- it will be reported as a proposed "
                                "module, not ticked. Add it to modules.core or "
                                "modules.buckets to make it real.")
    for f in (data.get("naming", {}).get("families") or []):
        if "pattern" not in f or "modules" not in f:
            problems.append(f"naming.families entry needs pattern+modules: {f!r}")
            continue
        try:
            re.compile(f["pattern"])
        except re.error as exc:
            problems.append(f"naming.families pattern {f['pattern']!r}: {exc}")
        for m in f["modules"]:
            if m not in vocab:
                problems.append(f"NOTE naming.families {f['pattern']!r} names {m!r}, "
                                "which has no tick column -- it will be proposed, "
                                "not ticked.")
    for a in (data.get("validation", {}).get("assertions") or []):
        for m in a.get("must_tick", []):
            if m not in vocab:
                problems.append(f"assertion {a.get('name')!r} requires {m!r}, which "
                                "has no tick column -- the assertion can never pass")
    return problems
