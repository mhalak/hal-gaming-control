"""One-screen HA app list editor: friendly names, verified raw identities.

The frontend receives only safe executable basenames and vetted Java
signatures. Adding a process requires an unchanged, fresh MQTT candidate;
renaming and removing old rows never send data to Windows.
"""
from .app_registry import MAX_APPS, identity_key, load_apps


class CandidateChanged(ValueError):
    """Foreground changed while a newly detected app was being enrolled."""


def raw_label(row):
    """Human-readable identity, never a private path or full command line."""
    name = row["process"]
    signature = row.get("signature")
    if signature:
        name += f" — {signature['kind']}: {signature['value']}"
    return name


def editor_choices(apps, candidate):
    """Existing processes and at most one fresh, uniquely identified candidate."""
    saved = load_apps(apps)
    choices = {raw_label(row): row for row in saved.values()}
    if isinstance(candidate, dict):
        try:
            key = identity_key(candidate["process"], candidate.get("signature"))
        except (KeyError, ValueError, TypeError):
            pass
        else:
            if key not in saved:
                choices[raw_label(candidate)] = candidate
    return choices


def editor_rows(apps):
    """Prepopulate editable rows in the same order as HA options."""
    return [{"name": row["name"], "detected": raw_label(row)}
            for row in load_apps(apps).values()]


def apply_app_editor(baseline, proposed, first_candidate, latest_candidate):
    """Apply one list edit, rejecting forged process IDs and stale additions.

    Existing rows can be renamed or deleted freely, but a new identity
    can ONLY equal the original candidate AND its freshly observed token.
    """
    old = load_apps(baseline)
    known = {raw_label(row): row for row in old.values()}
    choices = editor_choices(baseline, first_candidate)
    if not isinstance(proposed, list) or len(proposed) > MAX_APPS:
        raise ValueError("Invalid number of applications")

    result = []
    for item in proposed:
        if (not isinstance(item, dict) or set(item) != {"name", "detected"}
                or not isinstance(item["detected"], str)
                or item["detected"] not in choices):
            raise ValueError("Unknown application row")

        raw = item["detected"]
        if raw in known:
            source = known[raw]
        else:
            if not isinstance(first_candidate, dict):
                raise ValueError("Cannot add without a candidate")
            if (not isinstance(latest_candidate, dict)
                    or any(latest_candidate.get(field) != first_candidate.get(field)
                           for field in ("process", "signature", "token"))):
                raise CandidateChanged("Foreground application changed")
            source = first_candidate

        result.append({"process": source["process"],
                       "signature": source.get("signature"),
                       "name": item["name"]})

    # Reuse the existing strict validator for display names, duplicate
    # process signatures and forbidden bare Java, including max 64 apps.
    return list(load_apps(result).values())
