# __init__.py — External API clients for Stage 1 Discovery
from app.services.external_apis.motogp_client import fetch_motogp_pulselive
from app.services.external_apis.euroleague_client import fetch_euroleague_official
from app.services.external_apis.fiba_client import fetch_fiba_official
from app.services.external_apis.ibl_client import fetch_ibl_official_html
from app.services.external_apis.grand_slam_client import (
    fetch_wimbledon_official,
    fetch_us_open_official,
    fetch_australian_open_official,
    fetch_roland_garros_official,
)

__all__ = [
    "fetch_motogp_pulselive",
    "fetch_euroleague_official",
    "fetch_fiba_official",
    "fetch_ibl_official_html",
    "fetch_wimbledon_official",
    "fetch_us_open_official",
    "fetch_australian_open_official",
    "fetch_roland_garros_official",
]
