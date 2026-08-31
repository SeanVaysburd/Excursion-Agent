"""Smoke test: one read-only GET per data source, plus the film-filter
vocabulary dump for NYC events.

Run:  python -m scripts.smoke_test_apis

No keys required. If EBIRD_API_KEY is set in .env it is exercised (header
only -- the key is never printed); if not, the eBird check is skipped, which
is exactly the keyless mode the agent must survive.
"""

from __future__ import annotations

import os
from collections import Counter

import requests
from dotenv import load_dotenv

from src import config

load_dotenv()

T = 15  # timeout seconds
UA = {"User-Agent": config.USER_AGENT}


def check(name: str, url: str, params=None, extra_headers=None) -> requests.Response | None:
    try:
        r = requests.get(
            url, params=params, headers={**UA, **(extra_headers or {})}, timeout=T
        )
        ok = r.status_code == 200
        print(f"{'PASS' if ok else 'FAIL'}  {name:<22} HTTP {r.status_code}  {len(r.content)} bytes")
        return r if ok else None
    except Exception as e:  # noqa: BLE001 - a smoke test reports, never raises
        print(f"FAIL  {name:<22} {type(e).__name__}: {e}")
        return None


def main() -> None:
    lat, lon = config.HOME_LAT, config.HOME_LON

    check(
        "Open-Meteo",
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m",
            "forecast_days": 2,
            # The four pins that keep the weather gate honest (defaults are
            # GMT + metric):
            "timezone": "America/New_York",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
    )

    check("NWS active alerts", "https://api.weather.gov/alerts/active", {"point": f"{lat},{lon}"})

    check(
        "NOAA tides",
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
        {
            "product": "predictions",
            "datum": "MLLW",  # omission is a hard 400
            "interval": "hilo",  # without it: 240 rows/day
            "station": config.TIDE_STATION_DEFAULT,
            "date": "today",
            "time_zone": "lst_ldt",
            "units": "english",
            "format": "json",
        },
    )

    events = check(
        "NYC events",
        "https://data.cityofnewyork.us/resource/tvpp-9vvx.json",
        {"$select": "event_type", "$limit": 2000},
    )
    if events is not None:
        vocab = Counter(row.get("event_type", "<missing>") for row in events.json())
        print("      event_type vocabulary (sample of 2000 rows):")
        for value, n in vocab.most_common():
            marker = (
                "ALLOW"
                if value in config.EVENT_TYPE_ALLOW
                else "FILM-EXCLUDED"
                if value in config.EVENT_TYPE_EXCLUDED_FILM
                else "excluded"
            )
            print(f"        {n:>5}  {value:<32} {marker}")

    check(
        "iNaturalist v2",
        "https://api.inaturalist.org/v2/observations",
        {
            "taxon_id": 3,
            "lat": lat,
            "lng": lon,
            "radius": config.INAT_RADIUS_KM,
            "verifiable": "true",
            "per_page": 3,
            "fields": "id,observed_on,taxon.name,taxon.preferred_common_name",
        },
    )

    check(
        "MTA alerts",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fall-alerts.json",
    )

    ebird_key = os.environ.get("EBIRD_API_KEY")
    if ebird_key:
        check(
            "eBird",
            "https://api.ebird.org/v2/data/obs/geo/recent",
            {"lat": lat, "lng": lon, "dist": config.EBIRD_DIST_KM, "maxResults": 3},
            extra_headers={"X-eBirdApiToken": ebird_key},
        )
    else:
        print("SKIP  eBird                  no EBIRD_API_KEY set (keyless mode is supported)")

    print("\nAll read-only GETs; no credentials printed. Done.")


if __name__ == "__main__":
    main()
