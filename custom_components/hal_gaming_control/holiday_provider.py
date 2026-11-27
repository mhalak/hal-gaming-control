"""Load the native HA Holiday library without a competing dependency pin.

Calendar computation is local; HA may install its normal Holiday requirements
when explicitly requested. No PC data is sent to a calendar service.
"""
from datetime import date, timezone

from .public_holidays import CACHE, COUNTRY, ENABLED, validate_cache


def _countries():
    from holidays import list_supported_countries
    return sorted(list_supported_countries(include_aliases=False))


def build_calendar(country, now, provider, supported):
    """Validate each complete annual result; no regional/observance categories."""
    if country not in supported:
        raise ValueError("Unsupported public holiday country")
    stamp = now.astimezone(timezone.utc).isoformat()
    years = {}
    for year in (now.year - 1, now.year, now.year + 1):
        result = provider(country, subdiv=None, categories=("public",),
                          years=year, expand=False)
        if not isinstance(result, dict) or not result:
            raise ValueError("Empty or invalid public holiday calendar")
        if any(type(day) is not date or day.year != year for day in result):
            raise ValueError("Holiday provider returned a foreign date")
        years[str(year)] = {"dates": {day.isoformat(): name for day, name in sorted(result.items())},
                            "loaded_at": stamp}
    return validate_cache({"version": 1, "country": country, "years": years}, country)


def _load(country, now):
    from holidays import country_holidays
    return build_calendar(country, now, country_holidays, _countries())


async def _requirements(hass):
    from homeassistant.requirements import async_get_integration_with_requirements
    await async_get_integration_with_requirements(hass, "holiday")


async def async_countries(hass):
    await _requirements(hass)
    return await hass.async_add_import_executor_job(_countries)


async def async_load_calendar(hass, country, now):
    await _requirements(hass)
    return await hass.async_add_import_executor_job(_load, country, now)


def cache_needs_refresh(options, now):
    if options.get(ENABLED) is not True:
        return False
    try:
        cache = validate_cache(options.get(CACHE), options.get(COUNTRY))
    except (ValueError, TypeError, OverflowError):
        return True
    return any(str(year) not in cache["years"]
               for year in (now.year - 1, now.year, now.year + 1))


async def async_refresh_calendar(hass, entry, now):
    """Preserve the old calendar on failure and never overwrite concurrent edits."""
    before = entry.options
    if not cache_needs_refresh(before, now):
        return False
    country = before.get(COUNTRY)
    cache = await async_load_calendar(hass, country, now)
    current = entry.options
    if (current.get(ENABLED) is not True or current.get(COUNTRY) != country
            or current.get(CACHE) != before.get(CACHE)):
        return False
    return hass.config_entries.async_update_entry(
        entry, options=dict(current, **{CACHE: cache})) is not False
