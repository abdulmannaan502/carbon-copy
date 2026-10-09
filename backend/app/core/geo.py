"""Geographic helpers. Coordinates in this project are synthetic and describe no real person or place."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE_LATITUDE = 111.32


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi, d_lambda = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) enclosing a circle; used to pre-filter in SQL."""
    d_lat = radius_km / KM_PER_DEGREE_LATITUDE
    d_lon = radius_km / (KM_PER_DEGREE_LATITUDE * cos(radians(lat)))
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon
