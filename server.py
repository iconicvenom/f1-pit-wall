"""F1 2026 Fan Dashboard API — FastF1 + Jolpica + OpenF1."""

import os
import re
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional

import fastf1
import numpy as np
import pandas as pd
import requests
import uvicorn
from dotenv import load_dotenv
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

os.makedirs("./f1_cache", exist_ok=True)
fastf1.Cache.enable_cache("./f1_cache")

app = FastAPI(title="F1 Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jolpica (Ergast-compatible) — same API surface as f1dataR::load_standings()
JOLPICA_BASES = [
    "https://api.jolpi.ca/ergast/f1",
    "https://ergast.com/api/f1",
]
OPENF1 = "https://api.openf1.org/v1"
SPORTMONKS = "https://api.sportmonks.com/v3/motorsport"
SPORTMONKS_TOKEN = os.getenv("SPORTMONKS_API_TOKEN", "")
SPORTMONKS_SEASON_ID = os.getenv("SPORTMONKS_SEASON_ID", "26733")
_of1_cache: dict[str, Any] = {}
_of1_last_request: float = 0.0
_jolpica_down_until: float = 0.0
YEAR = 2026
_cache: dict[str, dict] = {}
CACHE_TTL = 600
F1_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}

TEAM_COLORS = {
    "mercedes": "#27F4D2",
    "ferrari": "#E8002D",
    "mclaren": "#FF8000",
    "red_bull": "#3671C6",
    "redbull": "#3671C6",
    "williams": "#64C4FF",
    "haas": "#B6BABD",
    "alpine": "#0093CC",
    "audi": "#00877C",
    "rb": "#6692FF",
    "racing_bulls": "#6692FF",
    "racingbulls": "#6692FF",
    "aston_martin": "#229971",
    "aston": "#229971",
    "cadillac": "#8A9099",
}

DRIVERS_2026 = [
    {"code": "VER", "number": 1, "given_name": "Max", "family_name": "Verstappen", "team_id": "red_bull", "team_name": "Red Bull Racing", "nationality": "NED"},
    {"code": "TSU", "number": 22, "given_name": "Yuki", "family_name": "Tsunoda", "team_id": "red_bull", "team_name": "Red Bull Racing", "nationality": "JPN"},
    {"code": "NOR", "number": 4, "given_name": "Lando", "family_name": "Norris", "team_id": "mclaren", "team_name": "McLaren", "nationality": "GBR"},
    {"code": "PIA", "number": 81, "given_name": "Oscar", "family_name": "Piastri", "team_id": "mclaren", "team_name": "McLaren", "nationality": "AUS"},
    {"code": "LEC", "number": 16, "given_name": "Charles", "family_name": "Leclerc", "team_id": "ferrari", "team_name": "Ferrari", "nationality": "MON"},
    {"code": "HAM", "number": 44, "given_name": "Lewis", "family_name": "Hamilton", "team_id": "ferrari", "team_name": "Ferrari", "nationality": "GBR"},
    {"code": "RUS", "number": 63, "given_name": "George", "family_name": "Russell", "team_id": "mercedes", "team_name": "Mercedes", "nationality": "GBR"},
    {"code": "ANT", "number": 12, "given_name": "Kimi", "family_name": "Antonelli", "team_id": "mercedes", "team_name": "Mercedes", "nationality": "ITA"},
    {"code": "ALO", "number": 14, "given_name": "Fernando", "family_name": "Alonso", "team_id": "aston_martin", "team_name": "Aston Martin", "nationality": "ESP"},
    {"code": "STR", "number": 18, "given_name": "Lance", "family_name": "Stroll", "team_id": "aston_martin", "team_name": "Aston Martin", "nationality": "CAN"},
    {"code": "GAS", "number": 10, "given_name": "Pierre", "family_name": "Gasly", "team_id": "alpine", "team_name": "Alpine", "nationality": "FRA"},
    {"code": "DOO", "number": 7, "given_name": "Jack", "family_name": "Doohan", "team_id": "alpine", "team_name": "Alpine", "nationality": "AUS"},
    {"code": "HUL", "number": 27, "given_name": "Nico", "family_name": "Hulkenberg", "team_id": "audi", "team_name": "Audi", "nationality": "GER"},
    {"code": "BOR", "number": 5, "given_name": "Gabriel", "family_name": "Bortoleto", "team_id": "audi", "team_name": "Audi", "nationality": "BRA"},
    {"code": "LAW", "number": 30, "given_name": "Liam", "family_name": "Lawson", "team_id": "racing_bulls", "team_name": "Racing Bulls", "nationality": "NZL"},
    {"code": "HAD", "number": 6, "given_name": "Isack", "family_name": "Hadjar", "team_id": "racing_bulls", "team_name": "Racing Bulls", "nationality": "FRA"},
    {"code": "OCO", "number": 31, "given_name": "Esteban", "family_name": "Ocon", "team_id": "haas", "team_name": "Haas F1 Team", "nationality": "FRA"},
    {"code": "BEA", "number": 87, "given_name": "Oliver", "family_name": "Bearman", "team_id": "haas", "team_name": "Haas F1 Team", "nationality": "GBR"},
    {"code": "ALB", "number": 23, "given_name": "Alexander", "family_name": "Albon", "team_id": "williams", "team_name": "Williams", "nationality": "THA"},
    {"code": "SAI", "number": 55, "given_name": "Carlos", "family_name": "Sainz", "team_id": "williams", "team_name": "Williams", "nationality": "ESP"},
    {"code": "BOT", "number": 77, "given_name": "Valtteri", "family_name": "Bottas", "team_id": "cadillac", "team_name": "Cadillac F1 Team", "nationality": "FIN"},
    {"code": "PER", "number": 11, "given_name": "Sergio", "family_name": "Perez", "team_id": "cadillac", "team_name": "Cadillac F1 Team", "nationality": "MEX"},
]

DRIVER_LOOKUP = {d["code"]: d for d in DRIVERS_2026}
NUMBER_LOOKUP = {d["number"]: d for d in DRIVERS_2026}


def cached(key: str, ttl: int = CACHE_TTL):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            now = time.time()
            if key in _cache and now - _cache[key]["t"] < ttl:
                return _cache[key]["v"]
            result = await fn(*args, **kwargs)
            _cache[key] = {"v": result, "t": now}
            return result

        return wrapper

    return decorator


def jolpica_get(path: str) -> Optional[dict]:
    """Fetch Jolpica/Ergast JSON — mirrors f1dataR REST calls."""
    global _jolpica_down_until
    if time.time() < _jolpica_down_until:
        return None
    headers = {"User-Agent": "F1Dashboard/1.0 (f1dataR-compatible)", "Accept": "application/json"}
    clean = path.lstrip("/")
    variants = [clean]
    if "Standings" in clean:
        variants.append(clean.replace("Standings", "standings"))
    elif "standings" in clean and "Standings" not in clean:
        variants.append(clean.replace("standings", "Standings"))
    for base in JOLPICA_BASES:
        for variant in variants:
            try:
                url = f"{base}/{variant}"
                r = requests.get(url, timeout=3, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    total = int(data.get("MRData", {}).get("total", 0))
                    if total > 0 or data.get("MRData", {}).get("RaceTable", {}).get("Races"):
                        return data
                    if data.get("MRData", {}).get("StandingsTable"):
                        return data
            except Exception:
                continue
    _jolpica_down_until = time.time() + 300
    return None


def jolpica_driver_standings(season: int = YEAR) -> Optional[dict]:
    for path in (
        f"{season}/driverstandings.json",
        f"{season}/driverStandings.json",
        f"{season}/last/driverstandings.json",
    ):
        data = jolpica_get(path)
        if data:
            return data
    return None


def jolpica_constructor_standings(season: int = YEAR) -> Optional[dict]:
    for path in (
        f"{season}/constructorstandings.json",
        f"{season}/constructorStandings.json",
        f"{season}/last/constructorstandings.json",
    ):
        data = jolpica_get(path)
        if data:
            return data
    return None


def safe_int(val, default: int = 0) -> int:
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return int(float(val))
    except Exception:
        return default


def normalize_team_id(name: str) -> str:
    n = (name or "").lower()
    for key, tid in (
        ("mclaren", "mclaren"), ("ferrari", "ferrari"), ("mercedes", "mercedes"),
        ("red bull", "red_bull"), ("williams", "williams"), ("haas", "haas"),
        ("alpine", "alpine"), ("audi", "audi"), ("racing bulls", "racing_bulls"),
        ("rb", "racing_bulls"), ("aston", "aston_martin"), ("cadillac", "cadillac"),
    ):
        if key in n:
            return tid
    return n.replace(" ", "_").replace("-", "_")


def points_for_position(pos) -> float:
    try:
        if pos is None or (isinstance(pos, float) and np.isnan(pos)):
            return 0
        return float(F1_POINTS.get(int(pos), 0))
    except Exception:
        return 0


def openf1_get(path: str, params: Optional[dict] = None) -> Optional[list]:
    global _of1_last_request
    headers = {"User-Agent": "F1Dashboard/1.0"}
    url = f"{OPENF1}/{path.lstrip('/')}"
    for attempt in range(3):
        elapsed = time.time() - _of1_last_request
        if elapsed < 0.4:
            time.sleep(0.4 - elapsed)
        try:
            _of1_last_request = time.time()
            r = requests.get(url, params=params, timeout=10, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else None
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
        except Exception:
            if attempt < 2:
                time.sleep(0.5)
    return None


def openf1_sessions(year: int = YEAR) -> list:
    key = f"sessions_{year}"
    if key in _of1_cache and time.time() - _of1_cache[key]["t"] < 300:
        return _of1_cache[key]["v"]
    data = openf1_get("sessions", {"year": year}) or []
    _of1_cache[key] = {"v": data, "t": time.time()}
    return data


def openf1_meetings(year: int = YEAR) -> list:
    key = f"meetings_{year}"
    if key in _of1_cache and time.time() - _of1_cache[key]["t"] < 300:
        return _of1_cache[key]["v"]
    data = openf1_get("meetings", {"year": year}) or []
    _of1_cache[key] = {"v": data, "t": time.time()}
    return data


def openf1_completed_races(year: int = YEAR) -> list:
    now = datetime.now(timezone.utc)
    races = []
    for s in openf1_sessions(year):
        if s.get("session_type") != "Race":
            continue
        end = s.get("date_end")
        if not end:
            continue
        try:
            if datetime.fromisoformat(end.replace("Z", "+00:00")) <= now:
                races.append(s)
        except Exception:
            pass
    return sorted(races, key=lambda x: x.get("date_start", ""))


def openf1_driver_map(session_key: int) -> dict[int, dict]:
    key = f"drivers_{session_key}"
    if key in _of1_cache and time.time() - _of1_cache[key]["t"] < 600:
        return _of1_cache[key]["v"]
    drivers = openf1_get("drivers", {"session_key": session_key}) or []
    mapped = {d["driver_number"]: d for d in drivers if d.get("driver_number") is not None}
    _of1_cache[key] = {"v": mapped, "t": time.time()}
    return mapped


def openf1_code_for_number(driver_number: int, driver_map: dict) -> str:
    d = driver_map.get(driver_number) or NUMBER_LOOKUP.get(driver_number, {})
    if isinstance(d, dict):
        return str(d.get("name_acronym") or d.get("code") or driver_number).upper()
    return str(driver_number)


def openf1_schedule() -> list:
    """Season schedule from OpenF1 meetings — used when Jolpica is unreachable."""
    meetings = [m for m in openf1_meetings(YEAR) if "Testing" not in m.get("meeting_name", "")]
    schedule = []
    now = datetime.now(timezone.utc)
    for i, m in enumerate(sorted(meetings, key=lambda x: x.get("date_start", "")), start=1):
        start = m.get("date_start")
        ed = None
        if start:
            try:
                ed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except Exception:
                ed = None
        schedule.append({
            "round": i,
            "short_name": m.get("meeting_name", f"Round {i}"),
            "country": m.get("country_name", ""),
            "locality": m.get("location", ""),
            "circuit": m.get("circuit_short_name", ""),
            "circuit_id": str(m.get("circuit_key", "")),
            "start_utc": ed.isoformat() if ed else None,
            "status": "done" if ed and ed <= now else "upcoming",
            "meeting_key": m.get("meeting_key"),
        })
    return schedule


def openf1_season_driver_map(year: int = YEAR) -> dict[int, dict]:
    """Reuse the latest race driver list for the whole season (fewer API calls)."""
    races = openf1_completed_races(year)
    if not races:
        return {}
    return openf1_driver_map(races[-1]["session_key"])


def openf1_compute_standings() -> tuple[list, list]:
    """Aggregate WDC/WCC from OpenF1 session_result — fast fallback when Jolpica is down."""
    cache_key = f"computed_standings_{YEAR}"
    if cache_key in _of1_cache and time.time() - _of1_cache[cache_key]["t"] < 300:
        return _of1_cache[cache_key]["v"]

    driver_acc: dict[str, dict] = {}
    team_acc: dict[str, dict] = {}
    driver_map = openf1_season_driver_map(YEAR)

    for race in openf1_completed_races(YEAR):
        sk = race["session_key"]
        results = openf1_get("session_result", {"session_key": sk}) or []
        for r in results:
            num = r.get("driver_number")
            code = openf1_code_for_number(num, driver_map)
            dmeta = DRIVER_LOOKUP.get(code, NUMBER_LOOKUP.get(num, {}))
            od = driver_map.get(num, {})
            team_name = od.get("team_name") or dmeta.get("team_name", "")
            tid = normalize_team_id(team_name) or dmeta.get("team_id", "unknown")
            pts = float(r.get("points") or 0)
            pos = safe_int(r.get("position"))

            if code not in driver_acc:
                driver_acc[code] = {
                    "code": code,
                    "given_name": dmeta.get("given_name", od.get("first_name", code)),
                    "family_name": dmeta.get("family_name", od.get("last_name", code)),
                    "short_name": dmeta.get("family_name", od.get("last_name", code)),
                    "permanent_number": dmeta.get("number", num),
                    "nationality": (dmeta.get("nationality", "") or "")[:3].upper(),
                    "team_id": tid,
                    "team_name": team_name,
                    "pts": 0.0,
                    "wins": 0,
                }
            driver_acc[code]["pts"] += pts
            if pos == 1:
                driver_acc[code]["wins"] += 1

            if tid not in team_acc:
                team_acc[tid] = {
                    "id": tid,
                    "name": team_name or tid,
                    "nationality": (dmeta.get("nationality", "") or "")[:3].upper(),
                    "pts": 0.0,
                    "wins": 0,
                }
            team_acc[tid]["pts"] += pts
            if pos == 1:
                team_acc[tid]["wins"] += 1

    drivers = sorted(driver_acc.values(), key=lambda x: (-x["pts"], x["code"]))
    leader_pts = drivers[0]["pts"] if drivers else 0
    for i, d in enumerate(drivers):
        d["pos"] = i + 1
        d["gap"] = int(d["pts"] - leader_pts)

    constructors = sorted(team_acc.values(), key=lambda x: (-x["pts"], x["id"]))
    leader_c = constructors[0]["pts"] if constructors else 1
    for i, c in enumerate(constructors):
        c["pos"] = i + 1
        c["pct"] = round(c["pts"] / leader_c * 100, 1) if leader_c else 0

    result = (drivers, constructors)
    _of1_cache[cache_key] = {"v": result, "t": time.time()}
    return result


def openf1_race_results(session_key: int) -> list:
    results = openf1_get("session_result", {"session_key": session_key}) or []
    driver_map = openf1_driver_map(session_key)
    formatted = []
    for r in results:
        num = r.get("driver_number")
        code = openf1_code_for_number(num, driver_map)
        od = driver_map.get(num, {})
        dmeta = DRIVER_LOOKUP.get(code, NUMBER_LOOKUP.get(num, {}))
        team_name = od.get("team_name") or dmeta.get("team_name", "")
        pos = safe_int(r.get("position"))
        if pos <= 0:
            continue
        formatted.append({
            "position": pos,
            "driver_number": safe_int(num),
            "abbreviation": code,
            "full_name": od.get("full_name") or f"{dmeta.get('given_name', '')} {dmeta.get('family_name', '')}".strip(),
            "team_name": team_name,
            "team_id": normalize_team_id(team_name),
            "time": str(r.get("duration", "")),
            "status": "DNF" if r.get("dnf") else ("DNS" if r.get("dns") else ("DSQ" if r.get("dsq") else "Finished")),
            "points": float(r.get("points") or 0),
            "fastest_lap": False,
            "laps": safe_int(r.get("number_of_laps")),
        })
    formatted.sort(key=lambda x: x["position"])
    return formatted


def openf1_championship_history() -> list:
    cumulative: dict[str, float] = {}
    history = []
    driver_map = openf1_season_driver_map(YEAR)
    for i, race in enumerate(openf1_completed_races(YEAR), start=1):
        sk = race["session_key"]
        for r in openf1_get("session_result", {"session_key": sk}) or []:
            code = openf1_code_for_number(r.get("driver_number"), driver_map)
            cumulative[code] = cumulative.get(code, 0) + float(r.get("points") or 0)
        ranked = sorted(cumulative.items(), key=lambda x: -x[1])[:10]
        drivers = [{
            "code": code,
            "short_name": DRIVER_LOOKUP.get(code, {}).get("family_name", code),
            "team_id": DRIVER_LOOKUP.get(code, {}).get("team_id", ""),
            "points": pts,
            "pos": idx + 1,
        } for idx, (code, pts) in enumerate(ranked)]
        history.append({
            "round": i,
            "race_name": race.get("session_name", f"Round {i}"),
            "date": race.get("date_start", ""),
            "drivers": drivers,
        })
    return history


def format_lap_time(td) -> Optional[str]:
    if td is None or (isinstance(td, float) and np.isnan(td)):
        return None
    try:
        if hasattr(td, "total_seconds"):
            total = td.total_seconds()
        else:
            total = float(td)
        if total <= 0 or np.isnan(total):
            return None
        minutes = int(total // 60)
        seconds = total % 60
        if minutes > 0:
            return f"{minutes}:{seconds:06.3f}"
        return f"{seconds:.3f}"
    except Exception:
        return None


def format_gap(seconds: float) -> str:
    if seconds is None or (isinstance(seconds, float) and (np.isnan(seconds) or seconds <= 0)):
        return "POLE"
    return f"+{seconds:.3f}"


def normalize_compound(compound) -> str:
    if compound is None or (isinstance(compound, float) and np.isnan(compound)):
        return "UNKNOWN"
    c = str(compound).upper()
    mapping = {
        "SOFT": "SOFT", "MEDIUM": "MEDIUM", "HARD": "HARD",
        "INTERMEDIATE": "INTERMEDIATE", "INTER": "INTERMEDIATE",
        "WET": "WET", "UNKNOWN": "UNKNOWN",
    }
    for k, v in mapping.items():
        if k in c:
            return v
    return "UNKNOWN"


def speed_color(speed: float) -> str:
    if speed < 150:
        return "#e10600"
    if speed <= 250:
        t = (speed - 150) / 100
        return "#d4a017"
    return "#00d2be"


def get_schedule_df():
    try:
        return fastf1.get_event_schedule(YEAR)
    except Exception:
        return None


def parse_event_date(row) -> Optional[datetime]:
    try:
        if "EventDate" in row and pd.notna(row["EventDate"]):
            dt = pd.Timestamp(row["EventDate"])
            if dt.tzinfo is None:
                dt = dt.tz_localize("UTC")
            return dt.to_pydatetime()
    except Exception:
        pass
    return None


def get_round_status(event_date: Optional[datetime], now: datetime) -> str:
    if event_date is None:
        return "upcoming"
    if event_date <= now:
        return "done"
    return "upcoming"


def get_last_completed_round(sched=None) -> int:
    if sched is None:
        sched = get_schedule_df()
    now = datetime.now(timezone.utc)
    last_round = 1
    if sched is not None and not sched.empty:
        for _, row in sched.iterrows():
            ed = parse_event_date(row)
            rnd = int(row.get("RoundNumber", row.get("round", 1)))
            if ed and ed <= now:
                last_round = rnd
    return last_round


def get_next_round(sched=None) -> int:
    if sched is None:
        sched = get_schedule_df()
    now = datetime.now(timezone.utc)
    if sched is not None and not sched.empty:
        for _, row in sched.iterrows():
            ed = parse_event_date(row)
            rnd = int(row.get("RoundNumber", row.get("round", 1)))
            if ed and ed > now:
                return rnd
    return get_last_completed_round(sched) + 1


def load_session(
    year: int,
    round_num: int,
    session_type: str,
    *,
    laps: bool = True,
    weather: Optional[bool] = None,
    messages: Optional[bool] = None,
):
    try:
        session = fastf1.get_session(year, round_num, session_type)
        if weather is None:
            weather = session_type in ("R", "FP1", "FP2", "FP3")
        if messages is None:
            messages = session_type == "R"
        session.load(laps=laps, telemetry=False, weather=weather, messages=messages)
        return session
    except Exception:
        return None


def load_session_results(year: int, round_num: int, session_type: str = "R"):
    """Light load for race results when Ergast points are missing."""
    return load_session(
        year, round_num, session_type,
        laps=False, weather=True, messages=(session_type == "R"),
    )


def extract_weather(session) -> dict:
    default = {
        "air_temp": None, "track_temp": None, "humidity": None,
        "wind_speed": None, "wind_direction": None, "rainfall": 0,
    }
    try:
        wd = session.weather_data
        if wd is not None and not wd.empty:
            return {
                "air_temp": round(float(wd["AirTemp"].mean()), 1) if "AirTemp" in wd else None,
                "track_temp": round(float(wd["TrackTemp"].mean()), 1) if "TrackTemp" in wd else None,
                "humidity": round(float(wd["Humidity"].mean()), 1) if "Humidity" in wd else None,
                "wind_speed": round(float(wd["WindSpeed"].mean()), 1) if "WindSpeed" in wd else None,
                "wind_direction": round(float(wd["WindDirection"].mean()), 0) if "WindDirection" in wd else None,
                "rainfall": int(wd["Rainfall"].max()) if "Rainfall" in wd else 0,
            }
    except Exception:
        pass
    return default


def _weather_has_values(weather: dict) -> bool:
    return any(
        weather.get(k) is not None
        for k in ("air_temp", "track_temp", "humidity", "wind_speed")
    )


def _round_weather_val(value: Any, digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, float) and np.isnan(value):
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _openf1_session_name(session_key: int) -> str:
    for session in openf1_sessions():
        if session.get("session_key") == session_key:
            return str(session.get("session_name") or session.get("session_type") or "Session")
    return "Session"


def _openf1_live_session_key() -> Optional[int]:
    now = datetime.now(timezone.utc)
    for session in openf1_sessions():
        try:
            start = datetime.fromisoformat(session["date_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(session["date_end"].replace("Z", "+00:00"))
            if start <= now <= end:
                return session.get("session_key")
        except Exception:
            continue
    return None


def openf1_weather_from_reading(reading: dict, session_name: str = "Session") -> dict:
    return {
        "air_temp": _round_weather_val(reading.get("air_temperature")),
        "track_temp": _round_weather_val(reading.get("track_temperature")),
        "humidity": _round_weather_val(reading.get("humidity")),
        "wind_speed": _round_weather_val(reading.get("wind_speed")),
        "wind_direction": _round_weather_val(reading.get("wind_direction"), 0),
        "rainfall": int(reading.get("rainfall") or 0),
        "session_name": session_name,
        "source": "openf1",
        "updated": reading.get("date"),
    }


def openf1_latest_weather() -> Optional[dict]:
    """Most recent track weather sample from OpenF1 (live or latest session)."""
    live_key = _openf1_live_session_key()
    if live_key:
        readings = openf1_get("weather", {"session_key": live_key}) or []
        if readings:
            latest = max(readings, key=lambda r: r.get("date", ""))
            return openf1_weather_from_reading(latest, _openf1_session_name(live_key))

    readings = openf1_get("weather", {"session_key": "latest"}) or []
    if not readings:
        return None
    latest = max(readings, key=lambda r: r.get("date", ""))
    sk = latest.get("session_key")
    return openf1_weather_from_reading(
        latest,
        _openf1_session_name(sk) if sk else "Latest",
    )


def extract_race_results(session) -> list:
    results = []
    try:
        res = session.results
        if res is not None and not res.empty:
            for _, row in res.iterrows():
                pos = row.get("Position")
                if pos is None or (isinstance(pos, float) and np.isnan(pos)):
                    pos = row.get("ClassifiedPosition")
                if pos is None or (isinstance(pos, float) and np.isnan(pos)):
                    continue
                pos = safe_int(pos)
                if pos <= 0:
                    continue
                pts = row.get("Points")
                if pts is None or (isinstance(pts, float) and np.isnan(pts)):
                    pts = points_for_position(pos)
                else:
                    pts = float(pts)
                results.append({
                    "position": pos,
                    "driver_number": safe_int(row.get("DriverNumber")),
                    "abbreviation": str(row.get("Abbreviation", "")),
                    "full_name": str(row.get("FullName", row.get("BroadcastName", ""))),
                    "team_name": str(row.get("TeamName", "")),
                    "team_id": normalize_team_id(str(row.get("TeamName", ""))) or str(row.get("TeamId", "")).lower().replace(" ", "_"),
                    "time": str(row.get("Time", row.get("Status", ""))),
                    "status": str(row.get("Status", "Finished") or "Finished"),
                    "points": pts,
                    "fastest_lap": bool(row.get("FastestLap", False)),
                    "laps": safe_int(row.get("Laps")),
                })
            results.sort(key=lambda x: x["position"])
    except Exception:
        pass
    return results


def extract_fastest_lap(session) -> dict:
    try:
        fl = session.laps.pick_fastest()
        if fl is not None and not fl.empty:
            driver = str(fl.get("Driver", ""))
            return {
                "driver": driver,
                "time": format_lap_time(fl["LapTime"]),
                "lap_number": int(fl.get("LapNumber", 0)),
            }
    except Exception:
        pass
    return {"driver": None, "time": None, "lap_number": None}


def extract_stints(session, top_n: int = 10) -> list:
    stints = []
    try:
        laps = session.laps
        if laps is None or laps.empty:
            return stints
        results = session.results
        top_drivers = []
        if results is not None and not results.empty:
            top_drivers = results.sort_values("Position").head(top_n)["Abbreviation"].tolist()
        for driver in top_drivers:
            dl = laps.pick_driver(driver)
            if dl is None or dl.empty:
                continue
            driver_stints = []
            for stint_num in sorted(dl["Stint"].dropna().unique()):
                stint_laps = dl[dl["Stint"] == stint_num]
                if stint_laps.empty:
                    continue
                compound = normalize_compound(stint_laps.iloc[0].get("Compound"))
                lap_start = int(stint_laps["LapNumber"].min())
                lap_end = int(stint_laps["LapNumber"].max())
                driver_stints.append({
                    "compound": compound,
                    "lap_start": lap_start,
                    "lap_end": lap_end,
                    "laps": lap_end - lap_start + 1,
                })
            stints.append({"driver": driver, "stints": driver_stints})
    except Exception:
        pass
    return stints


def extract_safety_car(session) -> list:
    sc_laps = []
    try:
        msgs = session.race_control_messages
        if msgs is not None and not msgs.empty:
            for _, row in msgs.iterrows():
                msg = str(row.get("Message", ""))
                if "SAFETY CAR" in msg.upper() or "VIRTUAL SAFETY CAR" in msg.upper():
                    sc_laps.append({
                        "lap": int(row.get("Lap", 0) or 0),
                        "message": msg,
                        "type": "VSC" if "VIRTUAL" in msg.upper() else "SC",
                    })
    except Exception:
        pass
    return sc_laps


def extract_race_control(session, limit: int = 8) -> list:
    msgs = []
    try:
        rc = session.race_control_messages
        if rc is not None and not rc.empty:
            for _, row in rc.tail(limit).iterrows():
                msg = str(row.get("Message", ""))
                flag = "GREEN"
                if "RED FLAG" in msg.upper():
                    flag = "RED"
                elif "SAFETY CAR" in msg.upper() or "VIRTUAL SAFETY CAR" in msg.upper():
                    flag = "YELLOW"
                elif "PENALTY" in msg.upper():
                    flag = "ORANGE"
                msgs.append({
                    "flag": flag,
                    "category": str(row.get("Category", "")),
                    "message": msg,
                    "lap": int(row.get("Lap", 0) or 0),
                })
    except Exception:
        pass
    return msgs


def jolpica_schedule() -> list:
    """Build season schedule from Jolpica/Ergast — no FastF1."""
    data = jolpica_get(f"{YEAR}.json")
    schedule = []
    now = datetime.now(timezone.utc)
    if not data:
        return schedule
    try:
        races = data["MRData"]["RaceTable"]["Races"]
        for race in races:
            rnd = int(race["round"])
            try:
                ed = datetime.strptime(race["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                ed = None
            circuit = race.get("Circuit", {})
            schedule.append({
                "round": rnd,
                "short_name": race.get("raceName", f"Round {rnd}"),
                "country": circuit.get("Location", {}).get("country", ""),
                "locality": circuit.get("Location", {}).get("locality", ""),
                "circuit": circuit.get("circuitName", ""),
                "circuit_id": circuit.get("circuitId", "").lower().replace("_", "_"),
                "start_utc": ed.isoformat() if ed else None,
                "status": "done" if ed and ed <= now else "upcoming",
            })
    except Exception:
        pass
    return schedule


def jolpica_completed_round() -> int:
    now = datetime.now(timezone.utc)
    last = 0
    for entry in jolpica_schedule():
        if entry.get("start_utc"):
            try:
                ed = datetime.fromisoformat(entry["start_utc"].replace("Z", "+00:00"))
                if ed <= now:
                    last = entry["round"]
            except Exception:
                pass
    return last


def jolpica_race_meta() -> dict:
    meta = {}
    for entry in jolpica_schedule():
        meta[entry["round"]] = {
            "race_name": entry["short_name"],
            "date": entry.get("start_utc", ""),
        }
    return meta


def fastf1_schedule_list() -> list:
    sched = get_schedule_df()
    now = datetime.now(timezone.utc)
    schedule = []
    if sched is None or sched.empty:
        return schedule
    for _, row in sched.iterrows():
        ed = parse_event_date(row)
        rnd = int(row.get("RoundNumber", row.get("round", 1)))
        schedule.append({
            "round": rnd,
            "short_name": str(row.get("EventName", row.get("Location", f"Round {rnd}"))),
            "country": str(row.get("Country", "")),
            "locality": str(row.get("Location", "")),
            "circuit": str(row.get("Location", "")),
            "circuit_id": str(row.get("EventFormat", row.get("Location", ""))).lower().replace(" ", "_"),
            "start_utc": ed.isoformat() if ed else None,
            "status": "done" if ed and ed <= now else "upcoming",
        })
    return schedule


def fastf1_compute_standings() -> tuple[list, list]:
    """Aggregate championship from cached FastF1 race sessions when Jolpica is down."""
    sched = get_schedule_df()
    last_round = get_last_completed_round(sched)
    driver_acc: dict[str, dict] = {}
    team_acc: dict[str, dict] = {}

    for rnd in range(1, last_round + 1):
        try:
            session = load_session(YEAR, rnd, "R", laps=True, weather=True, messages=True)
            if not session:
                continue
            results = extract_race_results(session)
            if not results:
                continue
            for r in results:
                code = r["abbreviation"]
                if not code:
                    continue
                tid = r["team_id"] or "unknown"
                meta = DRIVER_LOOKUP.get(code, {})
                if code not in driver_acc:
                    driver_acc[code] = {
                        "code": code,
                        "given_name": meta.get("given_name", r["full_name"].split()[0] if r["full_name"] else code),
                        "family_name": meta.get("family_name", r["full_name"].split()[-1] if r["full_name"] else ""),
                        "short_name": meta.get("family_name", code),
                        "permanent_number": meta.get("number", r["driver_number"]),
                        "nationality": meta.get("nationality", "")[:3].upper(),
                        "team_id": tid,
                        "team_name": r["team_name"] or meta.get("team_name", ""),
                        "pts": 0.0,
                        "wins": 0,
                    }
                driver_acc[code]["pts"] += r["points"]
                if r["position"] == 1:
                    driver_acc[code]["wins"] += 1
                if tid not in team_acc:
                    team_acc[tid] = {
                        "id": tid,
                        "name": r["team_name"] or tid,
                        "nationality": meta.get("nationality", "")[:3].upper(),
                        "pts": 0.0,
                        "wins": 0,
                    }
                team_acc[tid]["pts"] += r["points"]
                if r["position"] == 1:
                    team_acc[tid]["wins"] += 1
        except Exception:
            continue

    drivers = sorted(driver_acc.values(), key=lambda x: (-x["pts"], x["code"]))
    leader_pts = drivers[0]["pts"] if drivers else 0
    for i, d in enumerate(drivers):
        d["pos"] = i + 1
        d["gap"] = int(d["pts"] - leader_pts)

    constructors = sorted(team_acc.values(), key=lambda x: (-x["pts"], x["id"]))
    leader_c = constructors[0]["pts"] if constructors else 1
    for i, c in enumerate(constructors):
        c["pos"] = i + 1
        c["pct"] = round(c["pts"] / leader_c * 100, 1) if leader_c else 0

    return drivers, constructors


def get_combined_schedule() -> list:
    schedule = jolpica_schedule()
    if schedule:
        return schedule
    schedule = openf1_schedule()
    if schedule:
        return schedule
    return fastf1_schedule_list()


def get_completed_round() -> int:
    last = jolpica_completed_round()
    if last:
        return last
    of1_races = openf1_completed_races(YEAR)
    if of1_races:
        return len(of1_races)
    return get_last_completed_round()


def parse_jolpica_standings(ds_data, cs_data) -> tuple[list, list, Optional[str]]:
    drivers, constructors = [], []
    error_msg = None
    if ds_data:
        try:
            standings = ds_data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
            leader_pts = float(standings[0]["points"]) if standings else 1
            for s in standings:
                d = s["Driver"]
                c = s["Constructors"][0] if s.get("Constructors") else {}
                pts = float(s["points"])
                drivers.append({
                    "pos": int(s["position"]),
                    "code": d["code"],
                    "given_name": d["givenName"],
                    "family_name": d["familyName"],
                    "short_name": d.get("familyName", d["code"]),
                    "permanent_number": int(d.get("permanentNumber", 0) or 0),
                    "nationality": (d.get("nationality", "") or "")[:3].upper(),
                    "team_id": c.get("constructorId", "").lower(),
                    "team_name": c.get("name", ""),
                    "pts": pts,
                    "wins": int(s["wins"]),
                    "gap": int(pts - leader_pts),
                })
        except Exception as e:
            error_msg = str(e)
    if cs_data:
        try:
            standings = cs_data["MRData"]["StandingsTable"]["StandingsLists"][0]["ConstructorStandings"]
            leader_pts = float(standings[0]["points"]) if standings else 1
            for s in standings:
                c = s["Constructor"]
                pts = float(s["points"])
                constructors.append({
                    "pos": int(s["position"]),
                    "id": c["constructorId"],
                    "name": c["name"],
                    "nationality": (c.get("nationality", "") or "")[:3].upper(),
                    "pts": pts,
                    "wins": int(s["wins"]),
                    "pct": round(pts / leader_pts * 100, 1) if leader_pts else 0,
                })
        except Exception as e:
            error_msg = error_msg or str(e)
    return drivers, constructors, error_msg


@app.on_event("startup")
async def warmup():
    def load():
        try:
            get_schedule_df()
            openf1_sessions(YEAR)
        except Exception:
            pass

    threading.Thread(target=load, daemon=True).start()


@app.get("/api/standings")
@cached("standings", 300)
async def api_standings():
    """Standings: Jolpica (f1dataR) → OpenF1 → FastF1."""
    now = datetime.now(timezone.utc)
    source = "jolpica"
    error_msg = None
    ds_data = jolpica_driver_standings(YEAR)
    cs_data = jolpica_constructor_standings(YEAR) if ds_data else None
    drivers, constructors, error_msg = parse_jolpica_standings(ds_data, cs_data)

    if not drivers:
        drivers, constructors = openf1_compute_standings()
        source = "openf1"
    if not drivers:
        drivers, constructors = fastf1_compute_standings()
        source = "fastf1"

    schedule = get_combined_schedule()
    next_race = None
    last_round = get_completed_round()
    for entry in schedule:
        if entry.get("start_utc"):
            try:
                ed = datetime.fromisoformat(entry["start_utc"].replace("Z", "+00:00"))
                if ed > now and next_race is None:
                    next_race = {**entry, "name": entry["short_name"], "status": "upcoming"}
            except Exception:
                pass

    last_race_info = {"round": last_round, "short_name": "", "circuit": "", "country": "",
                      "podium": [], "fastest_lap": {}, "weather": {}, "stints": [], "qualifying": []}
    for s in schedule:
        if s["round"] == last_round:
            last_race_info["short_name"] = s["short_name"]
            last_race_info["circuit"] = s["circuit"]
            last_race_info["country"] = s["country"]
            break

    of1_races = openf1_completed_races(YEAR)
    if of1_races:
        last_of1 = of1_races[-1]
        if not last_race_info["short_name"]:
            last_race_info["short_name"] = last_of1.get("location", "Last Race")
            last_race_info["circuit"] = last_of1.get("circuit_short_name", "")
            last_race_info["country"] = last_of1.get("country_name", "")
        results = openf1_race_results(last_of1["session_key"])
        if results:
            last_race_info["podium"] = [r for r in results if r["position"] <= 3]
            last_race_info["results"] = results

    if not last_race_info.get("results"):
        try:
            session = load_session_results(YEAR, last_round, "R")
            if session:
                results = extract_race_results(session)
                if results:
                    last_race_info["podium"] = [r for r in results if r["position"] <= 3]
                    last_race_info["results"] = results
        except Exception:
            pass

    result = {
        "drivers": drivers,
        "constructors": constructors,
        "schedule": schedule,
        "next_race": next_race,
        "last_race": last_race_info,
        "year": YEAR,
        "source": source,
    }
    if not drivers:
        return JSONResponse(
            content={**result, "error": error_msg or "Standings unavailable", "fallback": True},
            status_code=206,
        )
    return result


@app.get("/api/last-race")
@cached("last_race", 600)
async def api_last_race():
    sched = get_schedule_df()
    rnd = get_last_completed_round(sched)
    source = "fastf1"
    session = load_session(YEAR, rnd, "R")
    if session:
        results = extract_race_results(session)
        if results:
            return {
                "round": rnd,
                "results": results,
                "fastest_lap": extract_fastest_lap(session),
                "weather": extract_weather(session),
                "safety_car": extract_safety_car(session),
                "stints": extract_stints(session),
                "race_control": extract_race_control(session),
                "source": source,
            }

    of1_races = openf1_completed_races(YEAR)
    if of1_races:
        last = of1_races[-1]
        sk = last["session_key"]
        results = openf1_race_results(sk)
        rc = openf1_get("race_control", {"session_key": sk}) or []
        rc_msgs = []
        for row in rc[-8:]:
            msg = row.get("message", "")
            flag = "GREEN"
            if "RED" in msg.upper():
                flag = "RED"
            elif "SAFETY" in msg.upper() or "VSC" in msg.upper():
                flag = "YELLOW"
            elif "PENALTY" in msg.upper():
                flag = "ORANGE"
            rc_msgs.append({
                "flag": flag,
                "category": row.get("category", ""),
                "message": msg,
                "lap": row.get("lap_number", 0),
            })
        return {
            "round": len(of1_races),
            "results": results,
            "fastest_lap": {"driver": None, "time": None, "lap_number": None},
            "weather": {},
            "safety_car": [],
            "stints": [],
            "race_control": rc_msgs,
            "source": "openf1",
            "session_name": last.get("location", ""),
        }

    return JSONResponse(
        content={"error": "Could not load race session", "fallback": True, "round": rnd},
        status_code=206,
    )


def openf1_qualifying_grid(round_num: Optional[int] = None) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    quali_sessions = sorted(
        [s for s in openf1_sessions(YEAR) if s.get("session_type") == "Qualifying"],
        key=lambda x: x.get("date_start", ""),
    )
    completed = []
    for s in quali_sessions:
        end = s.get("date_end")
        if not end:
            continue
        try:
            if datetime.fromisoformat(end.replace("Z", "+00:00")) <= now:
                completed.append(s)
        except Exception:
            pass
    if not completed:
        return None
    if round_num and 1 <= round_num <= len(completed):
        session = completed[round_num - 1]
        idx = round_num
    else:
        session = completed[-1]
        idx = len(completed)
    sk = session["session_key"]
    results = openf1_get("session_result", {"session_key": sk}) or []
    driver_map = openf1_driver_map(sk)
    grid = []
    pole_driver = None
    pole_time = None
    for r in sorted(results, key=lambda x: safe_int(x.get("position"), 99)):
        num = r.get("driver_number")
        code = openf1_code_for_number(num, driver_map)
        od = driver_map.get(num, {})
        dmeta = DRIVER_LOOKUP.get(code, {})
        durations = r.get("duration")
        q1 = q2 = q3 = None
        if isinstance(durations, list):
            if len(durations) > 0:
                q1 = format_lap_time(durations[0])
            if len(durations) > 1:
                q2 = format_lap_time(durations[1])
            if len(durations) > 2:
                q3 = format_lap_time(durations[2])
        best = q3 or q2 or q1
        pos = safe_int(r.get("position"))
        if pos == 1:
            pole_driver = code
            pole_time = best
        grid.append({
            "position": pos,
            "driver": code,
            "full_name": od.get("full_name", f"{dmeta.get('given_name', '')} {dmeta.get('family_name', '')}".strip()),
            "team_id": normalize_team_id(od.get("team_name", dmeta.get("team_name", ""))),
            "team_name": od.get("team_name", dmeta.get("team_name", "")),
            "q1": q1, "q2": q2, "q3": q3,
            "gap": "POLE" if pos == 1 else None,
        })
    return {"round": idx + 1, "pole_driver": pole_driver, "pole_time": pole_time, "grid": grid, "source": "openf1"}


@app.get("/api/qualifying")
@cached("qualifying", 600)
async def api_qualifying(round: Optional[int] = None):
    rnd = round or get_last_completed_round()
    of1 = openf1_qualifying_grid(rnd)
    if of1 and of1.get("grid"):
        return of1

    session = load_session(YEAR, rnd, "Q")
    if not session:
        return JSONResponse(content={"error": "Could not load qualifying", "fallback": True}, status_code=206)

    grid = []
    try:
        results = session.results
        pole_time = None
        pole_driver = None
        q_laps: dict[str, dict] = {}

        for driver in session.laps["Driver"].unique():
            dl = session.laps.pick_driver(driver)
            q_laps[driver] = {"q1": None, "q2": None, "q3": None}
            for q_num, col in [(1, "Q1"), (2, "Q2"), (3, "Q3")]:
                try:
                    q_session = dl[dl["Session"] == col] if "Session" in dl.columns else dl
                    if q_session is not None and not q_session.empty:
                        best = q_session.pick_fastest()
                        if best is not None and not best.empty:
                            q_laps[driver][f"q{q_num}"] = format_lap_time(best["LapTime"])
                except Exception:
                    pass
            if q_laps[driver]["q1"] is None:
                try:
                    valid = dl[dl["LapTime"].notna()]
                    if not valid.empty:
                        for stint in [1, 2, 3]:
                            stint_laps = valid[valid.get("Stint", pd.Series([1] * len(valid))) == stint] if "Stint" in valid.columns else valid
                            if not stint_laps.empty:
                                best = stint_laps.loc[stint_laps["LapTime"].idxmin()]
                                q_laps[driver][f"q{stint}"] = format_lap_time(best["LapTime"])
                except Exception:
                    pass

        if results is not None and not results.empty:
            for _, row in results.sort_values("Position").iterrows():
                driver = str(row.get("Abbreviation", ""))
                q1 = q_laps.get(driver, {}).get("q1")
                q2 = q_laps.get(driver, {}).get("q2")
                q3 = q_laps.get(driver, {}).get("q3")
                best_times = [t for t in [q3, q2, q1] if t]
                if pole_time is None and q3:
                    pole_time = q3
                    pole_driver = driver
                grid.append({
                    "position": int(row.get("Position", 0)),
                    "driver": driver,
                    "full_name": str(row.get("FullName", "")),
                    "team_id": str(row.get("TeamId", "")).lower(),
                    "team_name": str(row.get("TeamName", "")),
                    "q1": q1, "q2": q2, "q3": q3,
                    "gap": "POLE" if int(row.get("Position", 99)) == 1 else None,
                })

        if pole_time and grid:
            def parse_time(t):
                if not t:
                    return None
                parts = t.split(":")
                if len(parts) == 2:
                    return float(parts[0]) * 60 + float(parts[1])
                return float(parts[0])

            pt = parse_time(pole_time)
            for g in grid:
                bt = parse_time(g["q3"] or g["q2"] or g["q1"])
                if bt and pt and g["position"] != 1:
                    g["gap"] = format_gap(bt - pt)
                elif g["position"] == 1:
                    g["gap"] = "POLE"
    except Exception as e:
        return JSONResponse(content={"error": str(e), "fallback": True}, status_code=206)

    return {
        "round": rnd,
        "pole_driver": pole_driver,
        "pole_time": pole_time,
        "grid": grid,
    }


@app.get("/api/tire-strategy")
@cached("tire_strategy", 600)
async def api_tire_strategy():
    rnd = get_last_completed_round()
    session = load_session(YEAR, rnd, "R")
    if not session:
        return JSONResponse(content={"error": "No session", "fallback": True}, status_code=206)
    return {"round": rnd, "drivers": extract_stints(session, top_n=10)}


@app.get("/api/telemetry/{driver_code}")
@cached("telemetry", 600)
async def api_telemetry(driver_code: str):
    rnd = get_last_completed_round()
    session = load_session(YEAR, rnd, "Q")
    if not session:
        return JSONResponse(content={"error": "No session", "fallback": True}, status_code=206)
    try:
        laps = session.laps.pick_driver(driver_code.upper())
        lap = laps.pick_fastest()
        if lap is None or lap.empty:
            return JSONResponse(content={"error": f"No laps for {driver_code}", "fallback": True}, status_code=206)
        tel = lap.get_telemetry()
        tel = tel.iloc[::5]
        x_min, x_max = tel["X"].min(), tel["X"].max()
        y_min, y_max = tel["Y"].min(), tel["Y"].max()
        x_range = x_max - x_min or 1
        y_range = y_max - y_min or 1
        sectors = []
        for _, row in tel.iterrows():
            speed = float(row.get("Speed", 0))
            sectors.append({
                "x": (float(row["X"]) - x_min) / x_range,
                "y": (float(row["Y"]) - y_min) / y_range,
                "color": speed_color(speed),
            })
        return {
            "driver_code": driver_code.upper(),
            "lap_time": format_lap_time(lap["LapTime"]),
            "compound": normalize_compound(lap.get("Compound")),
            "distance": tel["Distance"].tolist(),
            "speed": tel["Speed"].tolist(),
            "throttle": tel["Throttle"].tolist() if "Throttle" in tel else [],
            "brake": tel["Brake"].tolist() if "Brake" in tel else [],
            "nGear": tel["nGear"].tolist() if "nGear" in tel else [],
            "drs": tel["DRS"].tolist() if "DRS" in tel else [],
            "sectors": sectors,
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e), "fallback": True}, status_code=206)


@app.get("/api/driver/{driver_code}")
@cached("driver", 600)
async def api_driver(driver_code: str):
    code = driver_code.upper()
    career = {"wins": 0, "poles": 0, "championships": 0, "seasons": 0}
    jdata = jolpica_get(f"drivers/{code.lower()}/results.json?limit=500")
    if jdata:
        try:
            results = jdata["MRData"]["RaceTable"]["Races"]
            career["seasons"] = len(set(r.get("season", YEAR) for r in results))
            for race in results:
                for res in race.get("Results", []):
                    if res["Driver"]["code"].upper() == code:
                        if res.get("grid") == "1":
                            career["poles"] += 1
                        if res.get("position") == "1":
                            career["wins"] += 1
        except Exception:
            pass

    standings = jolpica_driver_standings(YEAR)
    season = {"standing": 0, "wins": 0, "points": 0, "avg_finish": 0, "laps_led": 0}
    last_5 = []
    source = "jolpica"
    if standings:
        try:
            ds = standings["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
            for s in ds:
                if s["Driver"]["code"].upper() == code:
                    season["standing"] = int(s["position"])
                    season["wins"] = int(s["wins"])
                    season["points"] = float(s["points"])
                    break
        except Exception:
            pass

    if not season["points"]:
        of1_drivers, _ = openf1_compute_standings()
        for d in of1_drivers:
            if d["code"] == code:
                season["standing"] = d["pos"]
                season["wins"] = d["wins"]
                season["points"] = d["pts"]
                source = "openf1"
                break

    rnd = get_last_completed_round()
    session = load_session(YEAR, rnd, "R")
    if session:
        try:
            dl = session.laps.pick_driver(code)
            if dl is not None and not dl.empty:
                season["laps_led"] = int((dl["Position"] == 1).sum())
        except Exception:
            pass

    of1_races = openf1_completed_races(YEAR)
    for i, race in enumerate(of1_races[-5:], start=max(1, len(of1_races) - 4)):
        for r in openf1_race_results(race["session_key"]):
            if r["abbreviation"] == code:
                last_5.append({
                    "round": i,
                    "short_name": race.get("location", ""),
                    "pos": r["position"],
                    "points": r["points"],
                    "status": r["status"],
                })
                break

    if len(last_5) < 5:
        sched = get_schedule_df()
        if sched is not None:
            completed = get_last_completed_round(sched)
            for r in range(max(1, completed - 4), completed + 1):
                try:
                    s = load_session_results(YEAR, r, "R")
                    if s and s.results is not None:
                        for _, row in s.results.iterrows():
                            if str(row.get("Abbreviation", "")).upper() == code:
                                last_5.append({
                                    "round": r,
                                    "short_name": "",
                                    "pos": safe_int(row.get("Position")),
                                    "points": float(row.get("Points") or points_for_position(row.get("Position"))),
                                    "status": str(row.get("Status", "")),
                                })
                except Exception:
                    pass

    driver_info = next((d for d in DRIVERS_2026 if d["code"] == code), None)
    return {
        "code": code,
        "driver": driver_info,
        "career": career,
        "season": season,
        "last_5": last_5[-5:],
        "source": source,
    }


@app.get("/api/weather")
@cached("weather", 600)
async def api_weather():
    weather = openf1_latest_weather()
    if weather and _weather_has_values(weather):
        return weather

    sched = get_schedule_df()
    session = None
    session_name = "Race"
    for rnd, stype in (
        (get_last_completed_round(sched), "R"),
        (get_next_round(sched), "FP1"),
    ):
        session = load_session_results(YEAR, rnd, stype) or load_session(
            YEAR, rnd, stype, laps=False, weather=True, messages=False,
        )
        if session:
            session_name = stype
            break

    if session:
        weather = extract_weather(session)
        weather["session_name"] = session_name
        weather["source"] = "fastf1"
        if _weather_has_values(weather):
            return weather

    if weather:
        return JSONResponse(
            content={**weather, "error": "Weather readings unavailable", "fallback": True},
            status_code=206,
        )
    return JSONResponse(content={"error": "No weather data", "fallback": True}, status_code=206)


@app.get("/api/live")
@cached("live", 15)
async def api_live():
    now = datetime.now(timezone.utc)
    sessions = openf1_get("sessions", {"year": YEAR}) or []
    live_session = None
    for s in sessions:
        try:
            start = datetime.fromisoformat(s["date_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(s["date_end"].replace("Z", "+00:00"))
            if start <= now <= end:
                live_session = s
                break
        except Exception:
            pass

    if not live_session:
        return {"live": False, "session": None, "grid": [], "race_control": []}

    key = live_session.get("session_key")
    positions = openf1_get("position", {"session_key": key}) or []
    car_data = openf1_get("car_data", {"session_key": key}) or []
    race_control = openf1_get("race_control", {"session_key": key}) or []

    speed_map = {}
    for cd in car_data[-50:]:
        speed_map[cd.get("driver_number")] = cd.get("speed", 0)

    grid = []
    for p in sorted(positions, key=lambda x: x.get("position", 99))[-20:]:
        dn = p.get("driver_number")
        grid.append({
            "pos": p.get("position"),
            "driver_number": dn,
            "driver_code": p.get("name_acronym", ""),
            "short_name": p.get("full_name", ""),
            "team": p.get("team_name", ""),
            "team_color": p.get("team_colour", "#e10600"),
            "speed": speed_map.get(dn, 0),
            "gap_to_leader": p.get("gap_to_leader", ""),
        })

    rc_msgs = []
    for rc in (race_control or [])[-8:]:
        msg = rc.get("message", "")
        flag = "GREEN"
        if "RED" in msg.upper():
            flag = "RED"
        elif "SAFETY" in msg.upper() or "VSC" in msg.upper():
            flag = "YELLOW"
        elif "PENALTY" in msg.upper():
            flag = "ORANGE"
        rc_msgs.append({
            "flag": flag,
            "category": rc.get("category", ""),
            "message": msg,
            "lap": rc.get("lap_number", 0),
        })

    return {
        "live": True,
        "session": {
            "type": live_session.get("session_type", ""),
            "country": live_session.get("country_name", ""),
            "circuit": live_session.get("circuit_short_name", ""),
            "year": live_session.get("year", YEAR),
            "round": live_session.get("meeting_key", 0),
        },
        "grid": grid,
        "race_control": rc_msgs,
    }


@app.get("/api/championship-history")
@cached("championship_history", 1800)
async def api_championship_history():
    """Points progression: Jolpica (f1dataR) → OpenF1 → FastF1."""
    completed = get_completed_round()
    schedule = get_combined_schedule()
    race_meta = {s["round"]: {"race_name": s["short_name"], "date": s.get("start_utc", "")} for s in schedule}
    history = []
    source = "jolpica"

    for rnd in range(1, completed + 1):
        data = jolpica_get(f"{YEAR}/{rnd}/driverStandings.json")
        if data:
            try:
                meta = race_meta.get(rnd, {})
                standings = data["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
                drivers = [{
                    "code": s["Driver"]["code"],
                    "short_name": s["Driver"].get("familyName", s["Driver"]["code"]),
                    "team_id": s["Constructors"][0]["constructorId"] if s.get("Constructors") else "",
                    "points": float(s["points"]),
                    "pos": int(s["position"]),
                } for s in standings[:10]]
                history.append({
                    "round": rnd,
                    "race_name": meta.get("race_name", f"Round {rnd}"),
                    "date": meta.get("date", ""),
                    "drivers": drivers,
                })
                continue
            except Exception:
                pass

    if not history:
        history = openf1_championship_history()
        source = "openf1"

    if not history:
        cumulative: dict[str, float] = {}
        for rnd in range(1, completed + 1):
            try:
                session = load_session_results(YEAR, rnd, "R")
                if not session:
                    continue
                for r in extract_race_results(session):
                    code = r["abbreviation"]
                    if code:
                        cumulative[code] = cumulative.get(code, 0) + r["points"]
                meta = race_meta.get(rnd, {})
                ranked = sorted(cumulative.items(), key=lambda x: -x[1])[:10]
                drivers = [{
                    "code": code,
                    "short_name": DRIVER_LOOKUP.get(code, {}).get("family_name", code),
                    "team_id": DRIVER_LOOKUP.get(code, {}).get("team_id", ""),
                    "points": pts,
                    "pos": i + 1,
                } for i, (code, pts) in enumerate(ranked)]
                history.append({
                    "round": rnd,
                    "race_name": meta.get("race_name", f"Round {rnd}"),
                    "date": meta.get("date", ""),
                    "drivers": drivers,
                })
            except Exception:
                pass
        source = "fastf1"

    if not history:
        return JSONResponse(content={"error": "No history data", "fallback": True, "history": []}, status_code=206)
    return {"history": history, "source": source}


@app.get("/api/lap-comparison/{round}/{driver1}/{driver2}")
@cached("lap_comparison", 600)
async def api_lap_comparison(round: int, driver1: str, driver2: str):
    session = load_session(YEAR, round, "R")
    if not session:
        return JSONResponse(content={"error": "No session", "fallback": True}, status_code=206)
    d1, d2 = driver1.upper(), driver2.upper()
    try:
        laps1 = session.laps.pick_driver(d1)
        laps2 = session.laps.pick_driver(d2)
        d1_info = session.get_driver(d1)
        d2_info = session.get_driver(d2)
        comparison = []
        max_lap = max(
            int(laps1["LapNumber"].max()) if not laps1.empty else 0,
            int(laps2["LapNumber"].max()) if not laps2.empty else 0,
        )
        for lap_num in range(1, max_lap + 1):
            l1 = laps1[laps1["LapNumber"] == lap_num]
            l2 = laps2[laps2["LapNumber"] == lap_num]
            d1_ms = None
            d2_ms = None
            if not l1.empty and pd.notna(l1.iloc[0]["LapTime"]):
                d1_ms = l1.iloc[0]["LapTime"].total_seconds() * 1000
            if not l2.empty and pd.notna(l2.iloc[0]["LapTime"]):
                d2_ms = l2.iloc[0]["LapTime"].total_seconds() * 1000
            comparison.append({
                "lap": lap_num,
                "d1_time_ms": d1_ms,
                "d2_time_ms": d2_ms,
                "d1_pos": int(l1.iloc[0]["Position"]) if not l1.empty and pd.notna(l1.iloc[0].get("Position")) else None,
                "d2_pos": int(l2.iloc[0]["Position"]) if not l2.empty and pd.notna(l2.iloc[0].get("Position")) else None,
                "d1_compound": normalize_compound(l1.iloc[0].get("Compound")) if not l1.empty else None,
                "d2_compound": normalize_compound(l2.iloc[0].get("Compound")) if not l2.empty else None,
            })
        return {
            "round": round,
            "driver1": {"code": d1, "name": str(d1_info.get("FullName", d1)), "team_id": str(d1_info.get("TeamId", "")).lower()},
            "driver2": {"code": d2, "name": str(d2_info.get("FullName", d2)), "team_id": str(d2_info.get("TeamId", "")).lower()},
            "laps": comparison,
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e), "fallback": True}, status_code=206)


# Ergast / Jolpica circuit keys → Sportmonks venue name fragments
CIRCUIT_VENUE_HINTS: dict[str, list[str]] = {
    "bahrain": ["bahrain", "sakhir"],
    "jeddah": ["jeddah", "corniche"],
    "melbourne": ["albert park", "melbourne"],
    "suzuka": ["suzuka"],
    "shanghai": ["shanghai"],
    "miami": ["miami"],
    "imola": ["imola", "enzo e dino ferrari"],
    "monaco": ["monaco"],
    "montreal": ["gilles villeneuve", "montreal"],
    "barcelona": ["barcelona", "catalunya"],
    "spielberg": ["red bull ring", "spielberg"],
    "silverstone": ["silverstone"],
    "spa": ["spa", "francorchamps"],
    "hungaroring": ["hungaroring", "hungary"],
    "zandvoort": ["zandvoort"],
    "monza": ["monza"],
    "baku": ["baku"],
    "marina_bay": ["marina bay", "singapore"],
    "cota": ["americas", "cota", "austin"],
    "mexico_city": ["rodriguez", "mexico city", "hermanos"],
    "interlagos": ["interlagos", "jose carlos pace", "josé carlos pace", "sao paulo"],
    "las_vegas": ["las vegas", "vegas"],
}

# Public Sportmonks CDN layout images (v3 venue IDs) — used when API plan lacks /venues access
SPORTMONKS_CDN_TRACKS: dict[str, dict[str, Any]] = {
    "melbourne": {"id": 343575, "name": "Albert Park", "image_path": "https://cdn.sportmonks.com/images/core/venues/23/343575.png"},
    "shanghai": {"id": 343576, "name": "Shanghai International Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/24/343576.png"},
    "bahrain": {"id": 343578, "name": "Bahrain International Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/26/343578.png"},
    "jeddah": {"id": 343579, "name": "Jeddah Street Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/27/343579.png"},
    "miami": {"id": 343580, "name": "Miami International Autodrome", "image_path": "https://cdn.sportmonks.com/images/core/venues/28/343580.png"},
    "imola": {"id": 343581, "name": "Autodromo Enzo e Dino Ferrari", "image_path": "https://cdn.sportmonks.com/images/core/venues/29/343581.png"},
    "monaco": {"id": 343582, "name": "Circuit de Monaco", "image_path": "https://cdn.sportmonks.com/images/core/venues/30/343582.png"},
    "barcelona": {"id": 343583, "name": "Circuit de Catalunya", "image_path": "https://cdn.sportmonks.com/images/core/venues/31/343583.png"},
    "spielberg": {"id": 343585, "name": "Red Bull Ring", "image_path": "https://cdn.sportmonks.com/images/core/venues/1/343585.png"},
    "silverstone": {"id": 343586, "name": "Silverstone Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/2/343586.png"},
    "spa": {"id": 343587, "name": "Spa-Francorchamps", "image_path": "https://cdn.sportmonks.com/images/core/venues/3/343587.png"},
    "hungaroring": {"id": 343588, "name": "Hungaroring", "image_path": "https://cdn.sportmonks.com/images/core/venues/4/343588.png"},
    "zandvoort": {"id": 343589, "name": "Circuit Zandvoort", "image_path": "https://cdn.sportmonks.com/images/core/venues/5/343589.png"},
    "monza": {"id": 343590, "name": "Autodromo Nazionale Monza", "image_path": "https://cdn.sportmonks.com/images/core/venues/6/343590.png"},
    "baku": {"id": 343591, "name": "Baku City Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/7/343591.png"},
    "marina_bay": {"id": 343592, "name": "Marina Bay Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/8/343592.png"},
    "cota": {"id": 343593, "name": "Circuit of the Americas", "image_path": "https://cdn.sportmonks.com/images/core/venues/9/343593.png"},
    "mexico_city": {"id": 343594, "name": "Autodromo Hermanos Rodriguez", "image_path": "https://cdn.sportmonks.com/images/core/venues/10/343594.png"},
    "interlagos": {"id": 343595, "name": "Autodromo Jose Carlos Pace", "image_path": "https://cdn.sportmonks.com/images/core/venues/11/343595.png"},
    "las_vegas": {"id": 343596, "name": "Las Vegas Grand Prix", "image_path": "https://cdn.sportmonks.com/images/core/venues/12/343596.png"},
    "suzuka": {"id": 343577, "name": "Suzuka Circuit", "image_path": "https://cdn.sportmonks.com/images/core/venues/25/343577.png"},
}


def _norm_circuit_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _venue_metadata_value(metadata: list, code: str) -> Optional[str]:
    for item in metadata or []:
        dev = str(item.get("developer_name") or item.get("code") or "").upper()
        if code.upper() in dev or dev.endswith(code.upper()):
            values = item.get("values") or item.get("value") or {}
            if isinstance(values, dict):
                for key in ("length", "name", "turns", "direction", "type", "season"):
                    if values.get(key) not in (None, ""):
                        return str(values[key])
            elif values not in (None, ""):
                return str(values)
    return None


def _venue_lookup_keys(venue: dict) -> set[str]:
    keys: set[str] = set()
    name = str(venue.get("name") or "")
    name_norm = _norm_circuit_key(name)
    if name_norm:
        keys.add(name_norm)
    for hint_list in CIRCUIT_VENUE_HINTS.values():
        for hint in hint_list:
            hint_norm = _norm_circuit_key(hint)
            if hint_norm and (hint_norm in name_norm or name_norm in hint_norm or hint.lower() in name.lower()):
                keys.add(hint_norm)
    for circuit_key, hints in CIRCUIT_VENUE_HINTS.items():
        if any(h.lower() in name.lower() for h in hints):
            keys.add(circuit_key)
    metadata = venue.get("metadata") or []
    gp_name = _venue_metadata_value(metadata, "GRAND_PRIX_NAME")
    if gp_name:
        keys.add(_norm_circuit_key(gp_name))
    return keys


def _sportmonks_fetch_venues() -> list[dict]:
    if not SPORTMONKS_TOKEN:
        return []
    headers = {"Accept": "application/json"}
    endpoints = [
        f"{SPORTMONKS}/venues/seasons/{SPORTMONKS_SEASON_ID}",
        f"{SPORTMONKS}/venues",
    ]
    for endpoint in endpoints:
        page = 1
        venues: list[dict] = []
        try:
            while page <= 10:
                resp = requests.get(
                    endpoint,
                    params={
                        "api_token": SPORTMONKS_TOKEN,
                        "include": "metadata",
                        "per_page": 50,
                        "page": page,
                    },
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break
                payload = resp.json()
                batch = payload.get("data") or []
                if isinstance(batch, dict):
                    batch = [batch]
                venues.extend(batch)
                pagination = payload.get("pagination") or {}
                if not pagination.get("has_more"):
                    break
                page += 1
            if venues:
                return venues
        except Exception:
            continue
    return []


def _static_cdn_track_entries() -> list[dict]:
    entries = []
    for circuit_key, track in SPORTMONKS_CDN_TRACKS.items():
        keys = {_norm_circuit_key(circuit_key), circuit_key}
        for hint in CIRCUIT_VENUE_HINTS.get(circuit_key, []):
            keys.add(_norm_circuit_key(hint))
        keys.add(_norm_circuit_key(track["name"]))
        entries.append({
            "id": track["id"],
            "name": track["name"],
            "image_path": track["image_path"],
            "keys": sorted(k for k in keys if k),
        })
    return entries


def _sportmonks_track_entries() -> tuple[list[dict], str]:
    entries = []
    for venue in _sportmonks_fetch_venues():
        image_path = venue.get("image_path")
        if not image_path:
            continue
        metadata = venue.get("metadata") or []
        entries.append({
            "id": venue.get("id"),
            "name": venue.get("name"),
            "image_path": image_path,
            "latitude": venue.get("latitude"),
            "longitude": venue.get("longitude"),
            "length": _venue_metadata_value(metadata, "TRACK_LENGTH"),
            "turns": _venue_metadata_value(metadata, "TRACK_TURNS"),
            "direction": _venue_metadata_value(metadata, "TRACK_DIRECTION"),
            "track_type": _venue_metadata_value(metadata, "TRACK_TYPE"),
            "keys": sorted(_venue_lookup_keys(venue)),
        })
    if entries:
        return entries, "sportmonks"
    return _static_cdn_track_entries(), "sportmonks_cdn"


_thanks_log: list[dict] = []


@app.get("/api/tracks")
@cached("tracks", 86400)
async def api_tracks():
    """Sportmonks Motorsport API v3 venue layouts (replaces deprecated f1.sportmonks.com/api/v1.0/tracks)."""
    tracks, source = _sportmonks_track_entries()
    if not tracks:
        return JSONResponse(
            content={
                "configured": bool(SPORTMONKS_TOKEN),
                "tracks": [],
                "source": "sportmonks",
                "error": "No track images available",
                "fallback": True,
            },
            status_code=206,
        )
    payload: dict[str, Any] = {
        "configured": bool(SPORTMONKS_TOKEN),
        "tracks": tracks,
        "source": source,
        "season_id": SPORTMONKS_SEASON_ID,
    }
    if source == "sportmonks_cdn" and SPORTMONKS_TOKEN:
        payload["notice"] = (
            "Token saved but Motorsport API venues access is not enabled on this plan. "
            "Using public Sportmonks CDN track layout images."
        )
    elif not SPORTMONKS_TOKEN:
        payload["notice"] = "Using public Sportmonks CDN track layout images."
    return payload


@app.post("/api/thanks")
async def api_thanks(body: dict):
    entry = {
        "name": body.get("name", "Anonymous"),
        "message": body.get("message", "")[:280],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _thanks_log.append(entry)
    return {"received": True, "message": "Thank you!"}


@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


STATIC_DIR = Path(__file__).resolve().parent
if (STATIC_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
