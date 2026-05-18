# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Tests for the auth + origin gates on ``WebsocketCopilotHandler``.

The handler used to subclass raw ``tornado.websocket.WebSocketHandler``
with an empty ``open(self)`` body: no auth, no origin allowlist, no XSRF
check. A user with an authenticated Jupyter session in one tab visiting
attacker.example could complete the WS upgrade and drive the chat
tool-execution pipeline. The handler now inherits from ``JupyterHandler``
so ``check_origin`` consults ``allow_origin`` and ``open`` is gated by
``@tornado.web.authenticated``.

These tests pin the inheritance + decoration so a regression that drops
the mixin (or removes the decorator) fails here rather than ship.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import tornado.web
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.base.websocket import WebSocketMixin
from tornado import websocket
from tornado.httputil import HTTPServerRequest
from tornado.web import Application

from notebook_intelligence.extension import WebsocketCopilotHandler


def test_handler_inherits_from_jupyter_handler():
    # JupyterHandler in the MRO means check_origin / check_xsrf_cookie
    # come from Jupyter's hardened versions, not tornado's defaults.
    assert issubclass(WebsocketCopilotHandler, JupyterHandler)


def test_handler_inherits_websocket_mixin():
    # WebSocketMixin matches Jupyter's first-party WS handlers and
    # supplies the upgrade-aware prepare() that returns 403 instead of
    # redirecting an unauth WS request to the login page.
    assert issubclass(WebsocketCopilotHandler, WebSocketMixin)


def test_check_origin_resolves_to_websocket_mixin():
    # The WS-aware check_origin lives on WebSocketMixin and respects
    # both allow_origin and skip_check_origin. A future refactor that
    # reorders the bases so tornado.websocket.WebSocketHandler's
    # any-same-host default wins must fail here.
    method = WebsocketCopilotHandler.check_origin
    qualname = getattr(method, "__qualname__", "")
    assert qualname.startswith("WebSocketMixin"), qualname


def _construct_handler():
    """Build a handler against a permissive mock so we can call open()."""
    app = Mock(spec=Application)
    app.settings = {"jinja2_env": None, "headers": {}}
    app.ui_methods = {}
    app.ui_modules = {}
    app.transforms = []
    request = Mock(spec=HTTPServerRequest)
    request.connection = Mock()
    request.headers = {}
    with patch("notebook_intelligence.extension.ThreadSafeWebSocketConnector"), patch(
        "notebook_intelligence.extension.ai_service_manager"
    ), patch("notebook_intelligence.extension.github_copilot"):
        return WebsocketCopilotHandler(app, request)


def test_open_raises_when_unauthenticated():
    # Behavioral pin: the ws_authenticated decorator raises HTTPError(403)
    # when current_user is falsy. If the decorator is silently dropped in
    # a future refactor, this test catches it.
    handler = _construct_handler()
    handler._current_user = None
    with pytest.raises(tornado.web.HTTPError) as exc_info:
        handler.open()
    assert exc_info.value.status_code == 403
