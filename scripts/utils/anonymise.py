"""Vendor anonymisation for published outputs.

Section 6 of the SQL Server Developer Edition EULA — the licence the container
and the native install both accept — forbids disclosing benchmark results for
that product without Microsoft's written approval. The study measures it, so
everything that leaves this repository names it "Commercial System A" instead.

Scope, deliberately narrow
--------------------------
This applies to *published* artefacts: the analysis tables and the figures that
go into the paper and the thesis. It does not apply to the raw measurements,
`all_results.csv`, the campaign logs, or anything else in this repository, all
of which keep the real vendor name because they are the record that makes the
work reproducible and this repository is private. Anonymising the internal
record would buy nothing and cost the ability to check a number against the run
that produced it.

If this repository is ever made public, that reasoning stops holding and the
raw files become a disclosure in themselves. The git history would carry the
names regardless, so the answer then is a scrubbed export rather than a rename.

Oracle needs no such treatment. The Technology Network licence does forbid
publishing benchmark results, but the campaign runs on the Free image, whose
Free Use Terms do not — which is the reason the plan requires the free build.
"""

# Only the vendor whose licence requires it.
PUBLIC_NAME = {
    "sqlserver": "Commercial System A",
    "SQL Server": "Commercial System A",
}

# The footnote every table and figure caption carries, so the substitution is
# never silent. A reader who cannot tell that a system has been renamed cannot
# judge what the comparison is worth.
NOTE = ("Commercial System A is anonymised under section 6 of its licence, "
        "which forbids disclosing benchmark results without the vendor's "
        "written approval.")


def public(name, enabled=True):
    """The name to print, given the vendor key or label."""
    if not enabled:
        return name
    return PUBLIC_NAME.get(name, name)


def anonymised_any(names, enabled=True):
    """True if any of these names is being substituted, so a caller knows
    whether to print NOTE."""
    return enabled and any(n in PUBLIC_NAME for n in names)
