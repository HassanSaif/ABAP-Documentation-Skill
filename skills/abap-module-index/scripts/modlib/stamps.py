"""
stamps.py -- make staleness a gate failure instead of a human duty.

The pipeline deliberately caches: `scan` is the only step that reads the source tree,
so re-tuning rule tables and re-rendering is a matter of seconds. The price of that
design is a trap, and it is a nasty one because it fails QUIETLY: change
`packages.excluded`, re-run from `attribute` to save time, and the unit files are still
the ones built before the exclusion -- so third-party rows survive into a deliverable
that otherwise validates clean. (That is not hypothetical. It happened while building
this skill, and only the adversarial third-party check caught it.)

So every step records a fingerprint of the config sections it actually depends on. A
later step refuses to run on artefacts whose inputs have changed since, and names the
step to restart from. `--force` overrides, because sometimes you know better -- but you
have to say so.
"""

import hashlib
import json
import time

# Config sections each step's output depends on. Dotted paths into the site config;
# "knowledge" means the shipped SAP knowledge base (so updating the skill invalidates
# the right artefacts too).
DEPS = {
    "scan": ["paths.source_roots", "text.secondary_script", "knowledge.object_types",
             "knowledge.naming.custom_prefixes", "knowledge.std_tables",
             "knowledge.non_discriminating_tables"],
    "packages": ["paths.source_roots", "packages.providers", "packages.strip_prefixes",
                 "packages.root_package", "validation.held_out", "packages.map",
                 "packages.excluded"],
    "graph": ["knowledge.third_party", "extra_edge_files"],
    "units": ["packages.excluded", "knowledge.third_party", "knowledge.object_types",
              "knowledge.fold_edges", "tuning.max_hops"],
    "attribute": ["modules", "packages.map", "packages.excluded", "naming",
                  "naming.infrastructure_objects",
                  "text.keywords", "tuning", "knowledge"],
    "residual": ["modules", "packages.map", "naming", "text.keywords", "tuning",
                 "knowledge"],
    "discover": ["modules", "naming", "packages.map"],
    "overrides": ["modules"],
    "render": ["modules", "paths.out_prefix", "validation.thresholds"],
    "validate": ["validation", "modules", "packages.map"],
}
ORDER = ["scan", "packages", "graph", "units", "attribute", "residual", "discover",
         "overrides", "render", "validate"]
STAMP_FILE = "_stamps.json"


def _dig(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def fingerprint(cfg, step):
    payload = {}
    for path in DEPS.get(step, []):
        if path == "knowledge" or path.startswith("knowledge."):
            sub = path[len("knowledge."):] if path != "knowledge" else ""
            payload[path] = _dig(cfg.k, sub) if sub else cfg.k
        else:
            payload[path] = _dig(cfg.data, path)
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _path(cfg):
    return cfg.work(STAMP_FILE)


def load(cfg):
    p = _path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def record(cfg, step):
    data = load(cfg)
    data[step] = {"fingerprint": fingerprint(cfg, step),
                  "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _path(cfg).write_text(json.dumps(data, indent=2), encoding="utf-8")


def stale_before(cfg, step):
    """Earlier steps whose recorded inputs no longer match the current config."""
    data = load(cfg)
    out = []
    for earlier in ORDER[:ORDER.index(step)]:
        rec = data.get(earlier)
        if rec is None:
            continue            # never run in this work dir -- a missing-file error
        if rec["fingerprint"] != fingerprint(cfg, earlier):
            out.append(earlier)
    return out
