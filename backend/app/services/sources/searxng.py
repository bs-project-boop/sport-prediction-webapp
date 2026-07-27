"""SearXNG source adapter with explicit error handling and no import side effects."""
from __future__ import annotations
import json, os, urllib.error, urllib.parse, urllib.request
from typing import Any
from .exceptions import SourceUnavailableError
SEARXNG_URL=os.environ.get("SEARXNG_URL","http://10.10.10.5:8888")
SEARCH_PATH="/search"
SEARCH_TIMEOUT_SECONDS=25
HEALTHCHECK_TIMEOUT_SECONDS=8
USER_AGENT="sport-prediction-backend/1.0"
def _request_json(url: str, timeout: int) -> dict[str, Any]:
    """Decode JSON or raise SourceUnavailableError on request failure."""
    request=urllib.request.Request(url,headers={"User-Agent":USER_AGENT})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response: payload=json.loads(response.read())
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,UnicodeDecodeError) as exc:
        raise SourceUnavailableError(f"SearXNG request failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if not isinstance(payload,dict): raise SourceUnavailableError("SearXNG returned a non-object JSON response")
    return payload
def search(query: str, *, max_results: int=15, timeout: int=SEARCH_TIMEOUT_SECONDS) -> list[dict[str,Any]]:
    """Return unique scored results on success; raise SourceUnavailableError on failure."""
    params={"q":query,"format":"json","language":"en","safesearch":0,"categories":"general"}
    payload=_request_json(f"{SEARXNG_URL}{SEARCH_PATH}?{urllib.parse.urlencode(params)}",timeout)
    results=payload.get("results",[]) or []
    if not isinstance(results,list): raise SourceUnavailableError("SearXNG response field 'results' is not a list")
    seen={}
    for result in results:
        if isinstance(result,dict) and result.get("url") and result["url"] not in seen: seen[result["url"]]=result
    return sorted(seen.values(),key=lambda item: float(item.get("score") or 0),reverse=True)[:max_results]
def healthcheck(*, timeout: int=HEALTHCHECK_TIMEOUT_SECONDS) -> dict[str,Any]:
    """Run legacy q=ping healthcheck; return status or raise on failure."""
    payload=_request_json(f"{SEARXNG_URL}{SEARCH_PATH}?{urllib.parse.urlencode({'q':'ping','format':'json'})}",timeout)
    results=payload.get("results",[]) or []
    if not isinstance(results,list): raise SourceUnavailableError("SearXNG healthcheck returned invalid results")
    return {"ok":True,"results_count":len(results)}
