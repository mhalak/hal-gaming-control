"""Country-wide public holiday policy from a validated annual local cache.

No provider call or runtime mutation in the policy path. Missing, invalid or
foreign cache data retains the ordinary weekly rules with an unknown status.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import re

ENABLED = "public_holidays_enabled"
COUNTRY = "public_holiday_country"
CACHE = "public_holiday_cache"
MAX_YEARS = 3
MAX_DATES = 366


def _country(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{2}", value) is None:
        raise ValueError("Invalid public holiday country")
    return value


def _annual(year, row):
    if (not isinstance(year, str) or re.fullmatch(r"[0-9]{4}", year) is None
            or not isinstance(row, dict) or set(row) != {"dates", "loaded_at"}
            or not isinstance(row["dates"], dict)
            or not 0 < len(row["dates"]) <= MAX_DATES
            or not isinstance(row["loaded_at"], str)):
        raise ValueError("Invalid annual holiday cache")
    stamp = datetime.fromisoformat(row["loaded_at"])
    if stamp.utcoffset() != timedelta(0):
        raise ValueError("Holiday load timestamp must be UTC")
    for key, name in row["dates"].items():
        if (not isinstance(key, str) or date.fromisoformat(key).isoformat() != key
                or key[:4] != year or not isinstance(name, str)
                or not name.strip() or len(name) > 512
                or any(ord(char) < 32 for char in name)):
            raise ValueError("Invalid public holiday date or name")
    return row


def validate_cache(value, country):
    """Validate all persisted years before using any date as an entitlement."""
    _country(country)
    if (not isinstance(value, dict) or set(value) != {"version", "country", "years"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["country"] != country or not isinstance(value["years"], dict)
            or not 0 < len(value["years"]) <= MAX_YEARS):
        raise ValueError("Invalid public holiday cache")
    for year, row in value["years"].items():
        _annual(year, row)
    return value


def holiday_info(options, day):
    """Return independent calendar status and name for the requested local day."""
    if options.get(ENABLED) is not True:
        return {"status": "disabled", "name": None, "loaded_at": None}
    try:
        cache = validate_cache(options.get(CACHE), options.get(COUNTRY))
        annual = cache["years"].get(str(day.year))
    except (ValueError, TypeError, OverflowError):
        annual = None
    if annual is None:
        return {"status": "unknown", "name": None, "loaded_at": None}
    name = annual["dates"].get(day.isoformat())
    return {"status": "holiday" if name else "ordinary",
            "name": name, "loaded_at": annual["loaded_at"]}


def weekend_equivalent(options, day):
    """Only verified weekday holidays inherit weekend rules; never double grant."""
    return day.weekday() >= 5 or holiday_info(options, day)["status"] == "holiday"


def historical_holiday_policy(options):
    """Freeze the calendar used at grant time, not a later provider result."""
    if options.get(ENABLED) is not True:
        return {}
    try:
        cache = validate_cache(options.get(CACHE), options.get(COUNTRY))
    except (ValueError, TypeError, OverflowError):
        return {}  # Historical policy used the ordinary weekday fallback.
    return {ENABLED: True, COUNTRY: cache["country"], CACHE: deepcopy(cache)}


def holiday_receipt(options, day):
    """Read-only status for existing diagnostics; disabled installs stay unchanged."""
    if options.get(ENABLED) is not True:
        return {}
    info = holiday_info(options, day)
    return {"public_holiday_status": info["status"],
            "public_holiday_name": info["name"],
            "public_holiday_country": options.get(COUNTRY),
            "public_holiday_loaded_at": info["loaded_at"]}
