"""Client contract for POST /api/rebuild vs local POST /rebuild.

Keep ensureFreshDigest in index.html in sync with after_api_rebuild().
"""

# 404/403: no Vercel route. 405/501: python -m http.server (method not allowed).
API_REBUILD_TRY_LOCAL = frozenset((403, 404, 405, 501))


def after_api_rebuild(status):
    """What the app does after POST /api/rebuild.

    ok — use the response. poll — 202 accepted, wait on Blob.
    try_local — fall through to POST /rebuild. error — stop.
    """
    if status == 200:
        return "ok"
    if status == 202:
        return "poll"
    if status in API_REBUILD_TRY_LOCAL:
        return "try_local"
    return "error"
