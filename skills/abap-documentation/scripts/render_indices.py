#!/usr/bin/env python3
"""
abap-documentation Index Renderer — turns `docs/_index/raw/*.tsv` into
`docs/_index/<family>.md` markdown tables.

For each family that hides its friendly name behind an SAP-generated identifier,
the rendered markdown table shows BOTH columns visibly — never the on-disk name
alone. The methodology depends on this for navigation.

No third-party dependencies.

Usage:
    python render_indices.py [--repo-root .] [--index docs/_index/raw] [--output docs/_index]
"""

import argparse
import csv
import sys
from pathlib import Path


# (tsv-filename, output-md-filename, page title, columns to render [as TSV-key, display-header pairs], optional header note)
RENDER_CONFIG = [
    ("sicf.tsv", "sicf.md", "SICF / HTTP Service Nodes",
     [
         ("package", "Package"),
         ("icf_name", "ICF_NAME (on disk)"),
         ("icf_altnme", "Alias (`ICFALTNME`)"),
         ("handler", "Handler (first)"),
         ("handlers", "Full handler chain"),
         ("handler_count", "#"),
         ("file", "Source"),
     ],
     "HTTP service handlers active under `/sap/bc/...`. **Important — alias resolution:** "
     "Filenames use the SAP-generated `ICF_NAME` (often `DS41*`). The friendly name used "
     "in URLs is `ICFALTNME` inside the XML. Always check both columns when searching. "
     "**Handlers are a table, not a value:** a node may chain several handler classes in "
     "`ICFORDER` sequence, so read *Full handler chain*, not *Handler (first)*. "
     "**The handler class classifies the node:** an SAP Gateway OData handler "
     "(`/IWFND/CL_SODATA_HTTP_*`) means the node is a routing stub for the OData service "
     "of the same name and all analysis belongs in that service's doc; a customer-namespace "
     "handler means a bespoke inbound endpoint that needs its own drill-down; an empty "
     "handler table means a path-only node (index-only)."
    ),
    ("sush.tsv", "authorization_defaults.md", "Authorization Defaults (SU22/SU24)",
     [
         ("package", "Package"),
         ("guarded_name", "Guarded object"),
         ("guarded_type", "Type"),
         ("auth_objects", "Authorization object(s)"),
         ("okflag", "Checked?"),
         ("proposal", "Values proposed?"),
         ("sush_hash", "On-disk name"),
         ("file", "Source"),
     ],
     "**Which authorization object guards each externally-callable object.** This family answers "
     "the question section 7 of the doc template exists for, and it is the easiest family to miss: "
     "**the filename is an opaque hash** carrying no trace of what the object guards — the identity "
     "lives only in `<DISPLAY_NAME>` (`R3TR <TYPE> <NAME>`). Nothing here is a documentation gap; "
     "each entry is **index-only** and rides on the object it guards, whose §7 should cite it. "
     "Read two columns together: *Checked?* = `X` means the check really is performed at runtime, "
     "while *Values proposed?* = `No` means SU24 offers role maintenance **no default values** — the "
     "check is enforced but nobody is told how to populate it, which is the usual route to a blanket "
     "grant. **A 'no `AUTHORITY-CHECK` in the code' finding is incomplete until this table has been "
     "consulted.**"
    ),
    ("iwsv.tsv", "odata_services.md", "OData Service Definitions",
     [
         ("package", "Package"),
         ("tech_service_name", "Tech Name"),
         ("external_name", "External Name"),
         ("version", "Version"),
         ("file", "Source"),
     ],
     "Gateway OData service definitions (`*.iwsv.xml`). The `external_name` is the URL-facing name."
    ),
    ("iwsg.tsv", "odata_service_groups.md", "OData Service Groups",
     [
         ("package", "Package"),
         ("bep_service_name", "Service Name"),
         ("bep_technical_name", "Tech Name"),
         ("service_version", "Version"),
         ("file", "Source"),
     ],
     "Gateway service-group registrations. High cardinality — many are SAP-standard auto-activations."
    ),
    ("iwmo.tsv", "odata_models.md", "OData Model Definitions",
     [
         ("package", "Package"),
         ("model_name", "Model Name"),
         ("external_name", "External Name"),
         ("version", "Version"),
         ("file", "Source"),
     ],
     None,
    ),
    ("iwom.tsv", "odata_model_assignments.md", "OData Model Assignments",
     [
         ("package", "Package"),
         ("model_identifier", "Model Identifier"),
         ("external_name", "External Name"),
         ("sap_system", "SAP System"),
         ("file", "Source"),
     ],
     "Note: `model_identifier` carries the `_0001_BE` versioning suffix while `external_name` is the clean logical name."
    ),
    ("iwvb.tsv", "odata_vocab_bindings.md", "OData Vocabulary Bindings",
     [
         ("package", "Package"),
         ("anno_tech_name", "Annotation Tech Name"),
         ("serv_tech_name", "Service Tech Name"),
         ("file", "Source"),
     ],
     "Note: `_VAN` suffix on `anno_tech_name` is internal; `serv_tech_name` is the consumer-facing service."
    ),
    ("sxci.tsv", "sxci.md", "Classic BAdI Implementations (SXCI)",
     [
         ("package", "Package"),
         ("sxci_name", "Impl Name"),
         ("exit_name", "BAdI Definition"),
         ("impl_class", "Impl Class"),
         ("inter_name", "Interface"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     "Classic BAdI implementations. **Read with `enhancements.md`:** a MIGRATED classic BAdI is "
     "serialized TWICE -- once here and once as an ENHO -- and THE TWO NAMES OFTEN DIFFER (e.g. ENHO "
     "ZXX_ORDER_UPDATE_CHECK carries MIG_BADI_IMPL = ZXX_ORDER_RELEASE). The two families are "
     "deduplicated on the ENHO's `mig_badi_impl` column, not by name: distinct implementations = "
     "ENHO + SXCI - migrated twins. **An SXCI with no ENHO twin** is invisible to coverage unless "
     "this index is read."
    ),
    ("enho.tsv", "enhancements.md", "Enhancement Implementations",
     [
         ("package", "Package"),
         ("enh_name", "Impl Name"),
         ("enh_type", "Type"),
         ("badi_def", "BAdI Def"),
         ("spot_name", "Spot"),
         ("hook_target", "Hook Target"),
         ("impl_class", "Impl Class"),
         ("mig_badi_impl", "Migrated from (SXCI)"),
         ("file", "Source"),
     ],
     "BAdI / Hook / CLASENH implementations. Hidden field is the **target** spot (what the impl extends)."
    ),
    ("clas.tsv", "classes.md", "Classes",
     [
         ("package", "Package"),
         ("clsname", "Class Name"),
         ("superclass", "Superclass"),
         ("is_dpc_mpc", "DPC/MPC"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     "DPC/MPC base classes are auto-generated by Gateway — they don't get per-class docs."
    ),
    ("intf.tsv", "interfaces.md", "Interfaces",
     [
         ("package", "Package"),
         ("intf_name", "Interface Name"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("fugr.tsv", "function_groups.md", "Function Groups",
     [
         ("package", "Package"),
         ("fugr_name", "FG Name"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("fugr_fm.tsv", "function_modules.md", "Function Modules per FG",
     [
         ("package", "Package"),
         ("fugr_name", "FG Name"),
         ("fm_name", "FM Name"),
         ("kind", "Kind"),
         ("is_rfc", "RFC?"),
         ("file", "Source"),
     ],
     "RFC-enabled FMs are external-API touch points and bump the parent FG into 'substantive' scope."
    ),
    ("prog.tsv", "programs.md", "Programs",
     [
         ("package", "Package"),
         ("progname", "Program Name"),
         ("subc", "Type"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     "`subc`: 1=executable, I=include, M=module-pool, S=subroutine-pool."
    ),
    ("incl.tsv", "includes.md", "Include Programs",
     [
         ("package", "Package"),
         ("include_name", "Include Name"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     "Per methodology: includes are folded into using-program docs — no per-include drill-downs."
    ),
    ("ddls.tsv", "cds.md", "CDS DDL Views",
     [
         ("package", "Package"),
         ("view_name", "View Name"),
         ("label", "Label"),
         ("file", "Source"),
     ],
     None,
    ),
    ("tabl.tsv", "tables.md", "Tables (transparent / pool / cluster)",
     [
         ("package", "Package"),
         ("tabname", "Table Name"),
         ("tabclass", "Class"),
         ("ddtext", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("doma.tsv", "domains.md", "Domains",
     [
         ("package", "Package"),
         ("domname", "Domain Name"),
         ("ddtext", "Description"),
         ("file", "Source"),
     ],
     "Minor DDIC — referenced from using-object docs; no per-object drill-downs."
    ),
    ("dtel.tsv", "data_elements.md", "Data Elements",
     [
         ("package", "Package"),
         ("rollname", "Data Element"),
         ("ddtext", "Description"),
         ("file", "Source"),
     ],
     "Minor DDIC — referenced from using-object docs."
    ),
    ("msag.tsv", "message_classes.md", "Message Classes",
     [
         ("package", "Package"),
         ("arbgb", "Message Class"),
         ("stext", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("shlp.tsv", "search_helps.md", "Search Helps",
     [
         ("package", "Package"),
         ("shlpname", "Search Help"),
         ("ddtext", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("tobj.tsv", "maintenance_objects.md", "Table / View Maintenance Objects (TOBJ)",
     [
         ("package", "Package"),
         ("object", "Maintenance Object"),
         ("descript", "Description"),
         ("file", "Source"),
     ],
     "**These are NOT authorization objects** -- do not title or cite this page as such. "
     "abapGit's `TOBJ` is the SAP **table/view maintenance object** (`SOBJ`) -- an `SE54` generated "
     "maintenance dialog registration, carrying `TDDAT`/`TVDIR` and an authorization GROUP (`CCLASS`), "
     "very often `&NC&` meaning none. An authorization object serializes as **`SUSO`** "
     "(`*.suso.xml`) -- look there for the repository's real authorization objects. "
     "`OBJECTTYPE`: `S` = table maintenance, `V` = view maintenance, `C` = view cluster. "
     "**A `&NC&` row means anyone with generic table-maintenance rights can edit that table.**"
    ),
    ("tran.tsv", "tcodes.md", "Transaction Codes",
     [
         ("tcode", "T-Code"),
         ("pgmna", "Target Program"),
         ("dypno", "Screen"),
         ("ttext", "Description"),
         ("file", "Source"),
     ],
     None,
    ),
    ("sfpf.tsv", "adobe_forms.md", "Adobe Forms (layouts)",
     [
         ("package", "Package"),
         ("form_name", "Form"),
         ("interface", "Form Interface"),
         ("text", "Description"),
         ("file", "Source"),
     ],
     "**Sort by `Form Interface` before drilling.** The interface is the driver-to-layout contract: "
     "every form sharing one interface is fed by the same field set, and a change to the interface "
     "hits all of them. Forms and their interfaces routinely sit in different packages from the "
     "driver program that calls them, so never infer the driver from the package."
    ),
    ("sfpi.tsv", "adobe_form_interfaces.md", "Adobe Form Interfaces",
     [
         ("package", "Package"),
         ("interface_name", "Interface"),
         ("text", "Description"),
         ("file", "Source"),
     ],
     "Cross-reference against `adobe_forms.md` to find every layout bound to each interface."
    ),
    ("ssfo.tsv", "smart_forms.md", "Smart Forms",
     [
         ("package", "Package"),
         ("form_name", "Form"),
         ("interface", "Interface"),
         ("caption", "Caption"),
         ("file", "Source"),
     ],
     None,
    ),
    ("form.tsv", "sapscript_forms.md", "SAPscript Forms",
     [
         ("package", "Package"),
         ("form_name", "Form"),
         ("orig_lang", "Original Language"),
         ("text", "Description"),
         ("file", "Source"),
     ],
     "`Original Language` matters: a form whose original language is not the one you are reading "
     "may carry untranslated or mis-encoded text elements."
    ),
    ("pdts.tsv", "workflow_tasks.md", "Workflow Tasks (TS*)",
     [
         ("package", "Package"),
         ("task_id", "Task"),
         ("short_text", "Short Text"),
         ("impl_class", "Class"),
         ("impl_method", "Method"),
         ("background", "Bkgd"),
         ("rel_status", "Rel"),
         ("file", "Source"),
     ],
     "**`Class` / `Method` is the drill target and it is invisible from the filename**, which is the "
     "bare task number (`90000006.pdts.xml`). Workflow *tasks* (`TS*`, `.pdts`) are repository objects; "
     "workflow *templates* (`WS*`, `.pdws`) are configuration and are usually absent from the repo -- "
     "document those as config dependencies, never as pending docs. `Rel` = release status: a task that "
     "is not released cannot be started."
    ),
    ("sobj.tsv", "bor_object_types.md", "BOR Object Types",
     [
         ("package", "Package"),
         ("obj_type", "Object Type"),
         ("program", "Program"),
         ("kind", "Kind"),
         ("methods", "Meth"),
         ("attributes", "Attr"),
         ("events", "Evt"),
         ("interfaces", "Implemented Interfaces"),
         ("file", "Source"),
     ],
     "**A HOST family** -- each type gets a document (with its program on the `Covers:` line). "
     "BOR object types are the objects workflow tasks and events bind to; cross-reference against "
     "`workflow_tasks.md`. `Kind` decides the reading: a **subtype** inherits its supertype's code "
     "(read only the redefinitions); a **stand-alone** Z type has its own program -- check whether it "
     "is a verbatim copy of an SAP type (SAP note markers, German comments, no Z calls)."
    ),
    ("smtg.tsv", "email_templates.md", "E-mail Templates",
     [
         ("package", "Package"),
         ("template_id", "Template ID"),
         ("name", "Name"),
         ("cds_view", "Data source (CDS)"),
         ("parent_id", "Copied from"),
         ("file", "Source"),
     ],
     "**A HOST family.** The template ID can contain spaces and hyphens and is truncated in the "
     "filename -- use the `Template ID` column. Document templates by process in one catalogue "
     "document; check every link in the body for hard-coded system hosts."
    ),
    ("aqqu.tsv", "sap_queries.md", "SAP Queries (SQ01)",
     [
         ("package", "Package"),
         ("query", "Query"),
         ("user_group", "User group"),
         ("infoset", "InfoSet"),
         ("title", "Title"),
         ("file", "Source"),
     ],
     "**A HOST family.** Queries ARE serialized by abapGit (`AQQU`, with InfoSets `AQSG` and user "
     "groups `AQBG` as satellites). A transaction with `REPORTTYPE=AQ` in its `PARAM` launches one."
    ),
    ("wapa.tsv", "bsp_applications.md", "BSP / UI5 Applications",
     [
         ("package", "Package"),
         ("app_name", "BSP app"),
         ("app_id", "UI5 app id"),
         ("text", "Description"),
         ("page_count", "Files"),
         ("odata_services", "OData data sources"),
         ("file", "Source"),
     ],
     "**A HOST family.** The `OData data sources` column (from `manifest.json`) links each front end "
     "to its back-end service; document the app in, or next to, that service's document."
    ),
    ("dcls.tsv", "dcl_access_controls.md", "CDS Access Controls (DCL)",
     [
         ("package", "Package"),
         ("dcl_name", "DCL Role"),
         ("grants_on", "Grants On"),
         ("ddtext", "Description"),
         ("file", "Source"),
     ],
     "**This is the authorization layer for the CDS views** -- read it together with `cds.md`. "
     "A CDS view annotated `@AccessControl.authorizationCheck: #CHECK` needs a DCL role granting on it; "
     "one annotated `#NOT_REQUIRED` has explicitly opted out of any check. Compare the `Grants On` column "
     "against the `#CHECK` views: any `#CHECK` view absent from that column has **nothing enforcing it**. "
     "Note the source extension is `.dcls.asdcls`, **not** `.dcls.asddls` -- two transposed letters from "
     "the CDS view extension `.ddls.asddls`, and a documented cause of false 'no DCL exists' claims."
    ),
]


def render(tsv_path: Path, out_path: Path, title: str, columns: list[tuple[str, str]], note: str | None) -> int:
    if not tsv_path.exists():
        return -1
    with tsv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    if note:
        lines += [f"> {note}", ""]
    lines.append(f"**Total:** {len(rows)} rows.")
    lines.append("")
    if rows:
        header = "| " + " | ".join(disp for _, disp in columns) + " |"
        sep = "|" + "|".join(["---"] * len(columns)) + "|"
        lines += [header, sep]
        for r in rows:
            cells = []
            for key, _ in columns:
                v = (r.get(key) or "").strip()
                # Wrap object-name-ish columns in backticks for readability
                if key in {"icf_name", "icf_altnme", "tech_service_name", "external_name",
                          "bep_service_name", "bep_technical_name", "model_name", "model_identifier",
                          "anno_tech_name", "serv_tech_name", "enh_name", "spot_name", "hook_target",
                          "impl_class", "clsname", "superclass", "intf_name", "fugr_name", "fm_name",
                          "progname", "include_name", "view_name", "tabname", "domname", "rollname",
                          "arbgb", "shlpname", "object", "tcode", "pgmna", "file", "badi_def"}:
                    v = f"`{v}`" if v else ""
                cells.append(v)
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("*(no rows)*")
    # bytes, not write_text: on Windows text mode turns every \n into \r\n (CRLF indexes)
    out_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="abap-documentation index renderer.")
    ap.add_argument("--repo-root", default=".", help="Repo root.")
    ap.add_argument("--index", default="docs/_index/raw", help="TSV directory (relative to repo-root).")
    ap.add_argument("--output", default="docs/_index", help="Output directory for rendered markdown (relative to repo-root).")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    index_dir = (repo_root / args.index).resolve()
    output_dir = (repo_root / args.output).resolve()

    if not index_dir.exists():
        print(f"ERROR: index dir not found: {index_dir}", file=sys.stderr)
        print("  Run extract.py first to generate the TSVs.", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Rendering indexes from {index_dir} -> {output_dir}")

    n_rendered = 0
    for tsv_name, out_name, title, cols, note in RENDER_CONFIG:
        n = render(index_dir / tsv_name, output_dir / out_name, title, cols, note)
        if n < 0:
            print(f"  - {out_name}: (no TSV)")
        else:
            print(f"  - {out_name}: {n} rows")
            n_rendered += 1
    print(f"\nDone. Rendered {n_rendered} index pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
