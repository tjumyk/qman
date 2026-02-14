"""Auth decorators for API key and OAuth."""

import functools
from typing import Any, Callable

from flask import current_app, jsonify, request


def requires_api_key(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: require Basic auth with username 'api' and password = API_KEY."""

    @functools.wraps(f)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        api_key = current_app.config.get("API_KEY")
        if api_key is None:
            return jsonify(msg="api key not specified in app config"), 500
        auth = request.authorization
        if not auth:
            return jsonify(msg="authorization required"), 401
        if auth.username != "api" or auth.password != api_key:
            return jsonify(msg="access forbidden"), 403
        return f(*args, **kwargs)

    return wrapped
