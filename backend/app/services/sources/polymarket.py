"""Read-only Polymarket source adapter with explicit error handling."""
from __future__ import annotations
import json, urllib.error, urllib.parse, urllib.request
from typing import Any
from .exceptions import SourceUnavailableError
GAMMA_URL="https://gamma-api.polymarket.com"
CLOB_URL="https://clob.polymarket.com"
DATA_URL="https://data-api.polymarket.com"
REQUEST_TIMEOUT_SECONDS=15
USER_AGENT="sport-prediction-backend/1.0"
def _get(url: str, *, timeout: int=REQUEST_TIMEOUT_SECONDS) -> dict[str,Any]|list[Any]:
    """GET JSON or raise SourceUnavailableError; never terminate the process."""
    request=urllib.request.Request(url,headers={"User-Agent":USER_AGENT})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response: payload=json.loads(response.read().decode())
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,UnicodeDecodeError) as exc:
        raise SourceUnavailableError(f"Polymarket request failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if not isinstance(payload,(dict,list)): raise SourceUnavailableError("Polymarket returned invalid JSON")
    return payload
def _parse_json_field(value: Any)->Any:
    """Parse legacy double-encoded JSON fields when present."""
    if isinstance(value,str):
        try: return json.loads(value)
        except (json.JSONDecodeError,TypeError): return value
    return value
def search_markets(query: str)->dict[str,Any]:
    """Return public-search response or raise SourceUnavailableError."""
    payload=_get(f"{GAMMA_URL}/public-search?{urllib.parse.urlencode({'q':query})}")
    if not isinstance(payload,dict): raise SourceUnavailableError("Polymarket search response is not an object")
    return payload
def trending_events(limit: int=10)->list[Any]:
    """Return active open events ordered by volume."""
    params={"limit":limit,"active":"true","closed":"false","order":"volume","ascending":"false"}
    payload=_get(f"{GAMMA_URL}/events?{urllib.parse.urlencode(params)}")
    if not isinstance(payload,list): raise SourceUnavailableError("Polymarket trending response is not a list")
    return payload
def get_market(slug: str)->list[Any]:
    """Return markets matching slug; empty means no match."""
    payload=_get(f"{GAMMA_URL}/markets?{urllib.parse.urlencode({'slug':slug})}")
    if not isinstance(payload,list): raise SourceUnavailableError("Polymarket market response is not a list")
    return payload
def get_event(slug: str)->list[Any]:
    """Return events matching slug; empty means no match."""
    payload=_get(f"{GAMMA_URL}/events?{urllib.parse.urlencode({'slug':slug})}")
    if not isinstance(payload,list): raise SourceUnavailableError("Polymarket event response is not a list")
    return payload
def get_price(token_id: str)->dict[str,Any]:
    """Return buy, midpoint, and spread responses for a token."""
    buy=_get(f"{CLOB_URL}/price?{urllib.parse.urlencode({'token_id':token_id,'side':'buy'})}")
    midpoint=_get(f"{CLOB_URL}/midpoint?{urllib.parse.urlencode({'token_id':token_id})}")
    spread=_get(f"{CLOB_URL}/spread?{urllib.parse.urlencode({'token_id':token_id})}")
    if not all(isinstance(item,dict) for item in (buy,midpoint,spread)): raise SourceUnavailableError("Polymarket price response is malformed")
    return {"buy":buy,"midpoint":midpoint,"spread":spread}
def get_orderbook(token_id: str)->dict[str,Any]:
    """Return decoded orderbook for a token."""
    payload=_get(f"{CLOB_URL}/book?{urllib.parse.urlencode({'token_id':token_id})}")
    if not isinstance(payload,dict): raise SourceUnavailableError("Polymarket orderbook response is not an object")
    return payload
def get_price_history(condition_id: str, interval: str="all", fidelity: int=50)->dict[str,Any]:
    """Return price history for a market condition."""
    payload=_get(f"{CLOB_URL}/prices-history?{urllib.parse.urlencode({'market':condition_id,'interval':interval,'fidelity':fidelity})}")
    if not isinstance(payload,dict): raise SourceUnavailableError("Polymarket history response is not an object")
    return payload
def get_trades(limit: int=10, market: str|None=None)->list[Any]:
    """Return recent public trades; empty means no trades matched."""
    params={"limit":limit}
    if market: params["market"]=market
    payload=_get(f"{DATA_URL}/trades?{urllib.parse.urlencode(params)}")
    if not isinstance(payload,list): raise SourceUnavailableError("Polymarket trades response is not a list")
    return payload
__all__=["GAMMA_URL","CLOB_URL","DATA_URL","REQUEST_TIMEOUT_SECONDS","search_markets","trending_events","get_market","get_event","get_price","get_orderbook","get_price_history","get_trades","_parse_json_field"]
