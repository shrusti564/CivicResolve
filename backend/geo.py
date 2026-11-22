
import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = ROOT / "data" / "raw" / "gba_wards_2025.geojson"


@lru_cache(maxsize=1)
def load_ward_boundaries():
    """Load and cache the 369 GBA ward polygons."""
    if not BOUNDARY_PATH.exists():
        raise FileNotFoundError(
            f"Ward boundary dataset not found: {BOUNDARY_PATH}"
        )

    with open(BOUNDARY_PATH, encoding="utf-8") as file:
        data = json.load(file)

    wards = []

    for feature in data.get("features", []):
        geometry = feature.get("geometry")
        properties = feature.get("properties") or {}

        if not geometry:
            continue

        polygon = shape(geometry)

        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        if polygon.is_empty:
            continue

        wards.append({
            "geometry": polygon,
            "properties": properties
        })

    return wards


def lookup_ward(latitude: float, longitude: float):
    """
    Identify the GBA ward containing a GPS coordinate.

    GeoJSON uses longitude as X and latitude as Y.
    Ward identity uses unique id2, not ward_id alone.
    """

    if latitude is None or longitude is None:
        return {
            "matched": False,
            "reason": "GPS coordinates are missing"
        }

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {
            "matched": False,
            "reason": "Invalid GPS coordinates"
        }

    try:
        wards = load_ward_boundaries()
        point = Point(longitude, latitude)

        for ward in wards:
            if ward["geometry"].covers(point):
                props = ward["properties"]

                return {
                    "matched": True,
                    "ward_name": props.get("ward_name"),
                    "ward_name_kn": props.get("ward_name_kn"),
                    "ward_id": str(props.get("ward_id", "")),
                    "ward_feature_id": props.get("id2"),
                    "corporation": props.get("Corporation"),
                    "corporation_id": str(
                        props.get("corporation_id", "")
                    ),
                    "zone": props.get("zone_name"),
                    "assembly_constituency": props.get("Assembly"),
                    "ro_division": props.get("RO_Division"),
                    "aro_subdivision": props.get("ARO_ Sub Division"),
                    "boundary_version": "GBA 2025",
                    "boundary_source": "gba_wards_2025.geojson"
                }

        return {
            "matched": False,
            "reason": "Location is outside the available GBA ward boundaries",
            "latitude": latitude,
            "longitude": longitude
        }

    except FileNotFoundError as error:
        return {
            "matched": False,
            "reason": str(error)
        }

    except Exception as error:
        return {
            "matched": False,
            "reason": f"Ward lookup error: {error}"
        }
