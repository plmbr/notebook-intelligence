# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

"""Parametrized coverage for the `PolicyGatedHandler.prepare()` chokepoint
across all three management surfaces (Skills, Claude MCP, Plugins).

Each handler family wires its own attribute name into `policy_enabled_attr`
and its own user-facing message into `policy_disabled_message`. The mixin's
job is uniform: short-circuit with 403 when force-off and pass through
otherwise. Three parameter sets exercise that contract once per family.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from tornado.testing import AsyncHTTPTestCase

from notebook_intelligence.extension import (
    ClaudeMCPBaseHandler,
    ClaudeMCPListHandler,
    PluginsBaseHandler,
    PluginsListHandler,
    SkillsBaseHandler,
    SkillsListHandler,
)


HANDLER_FAMILIES = [
    pytest.param(
        SkillsBaseHandler,
        SkillsListHandler,
        "skills_management_enabled",
        "Skills management is disabled by your administrator",
        id="skills",
    ),
    pytest.param(
        ClaudeMCPBaseHandler,
        ClaudeMCPListHandler,
        "claude_mcp_management_enabled",
        "Claude MCP management is disabled by your administrator",
        id="claude_mcp",
    ),
    pytest.param(
        PluginsBaseHandler,
        PluginsListHandler,
        "claude_plugins_management_enabled",
        "Plugins management is disabled by your administrator",
        id="claude_plugins",
    ),
]


def _run_prepare(base_cls, handler):
    """Drive the mixin's `prepare()` with the parent's `prepare` stubbed
    out — bypasses jupyter_server's auth plumbing so we exercise just the
    gate."""
    from jupyter_server.base.handlers import APIHandler

    async def _noop(_self):
        return None

    with patch.object(APIHandler, "prepare", _noop):
        asyncio.run(base_cls.prepare(handler))


@pytest.mark.parametrize("base_cls,list_cls,attr,message", HANDLER_FAMILIES)
class TestPolicyGate:
    def test_default_attribute_allows(self, base_cls, list_cls, attr, message):
        assert getattr(base_cls, attr) is True

    def test_default_message_matches_subclass(
        self, base_cls, list_cls, attr, message
    ):
        assert base_cls.policy_disabled_message == message

    def test_prepare_rejects_when_disabled(
        self, base_cls, list_cls, attr, message
    ):
        handler = MagicMock(spec=list_cls)
        handler._finished = False
        handler.policy_enabled_attr = attr
        handler.policy_disabled_message = message
        setattr(handler, attr, False)

        def _finish(payload):
            handler._finished = True
            handler._finish_payload = payload

        handler.finish.side_effect = _finish
        _run_prepare(base_cls, handler)
        handler.set_status.assert_called_with(403)
        body = json.loads(handler._finish_payload)
        assert body["error"] == message

    def test_prepare_passes_when_enabled(
        self, base_cls, list_cls, attr, message
    ):
        handler = MagicMock(spec=list_cls)
        handler._finished = False
        handler.policy_enabled_attr = attr
        setattr(handler, attr, True)
        _run_prepare(base_cls, handler)
        handler.set_status.assert_not_called()
        handler.finish.assert_not_called()


class TestPolicyGateIntegration(AsyncHTTPTestCase):
    """End-to-end dispatch test that uses the *real* PolicyGatedHandler.

    Earlier versions of this test re-implemented the gate body in the test
    itself, so a regression in production would not have been caught. We
    now subclass ``PolicyGatedHandler`` directly and patch only the
    auth-bearing ``APIHandler.prepare`` to a no-op coroutine — that lets us
    drive the real prepare() chokepoint without setting up cookie_secret
    and identity_provider for every test.

    Asserts:
      * gate runs *after* ``await super().prepare()``
      * gate respects an already-finished request (the ``_finished`` guard)
      * gate short-circuits with 403 + JSON error on force-off
      * gate is a no-op when enabled (handler method runs)
    """

    DISABLED_MESSAGE = "the gate is force-off"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from jupyter_server.base.handlers import APIHandler

        async def _noop(_self):
            return None

        cls._api_handler_patcher = patch.object(APIHandler, "prepare", _noop)
        cls._api_handler_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._api_handler_patcher.stop()
        super().tearDownClass()

    def get_app(self):
        from notebook_intelligence.extension import PolicyGatedHandler
        from tornado.web import Application

        class _PassthroughGate(PolicyGatedHandler):  # type: ignore[misc]
            policy_enabled_attr = "gate_enabled"
            policy_disabled_message = TestPolicyGateIntegration.DISABLED_MESSAGE
            gate_enabled = True

            async def get(self):
                self.set_status(200)
                self.finish(json.dumps({"ok": True}))

        class _ParentFinishesEarly(PolicyGatedHandler):  # type: ignore[misc]
            """Override prepare to finish before the gate body runs via
            super, simulating an APIHandler that rejected auth. The gate
            must not overwrite the early finish."""

            policy_enabled_attr = "gate_enabled"
            policy_disabled_message = TestPolicyGateIntegration.DISABLED_MESSAGE
            gate_enabled = False  # force-off — but parent finishes first

            async def prepare(self):
                self.set_status(401)
                self.finish(json.dumps({"error": "from parent"}))
                # Now invoke the real chokepoint via super — it must respect
                # ``_finished`` and not overwrite the 401 with 403.
                await super().prepare()

            async def get(self):
                self.set_status(200)

        self._passthrough_cls = _PassthroughGate
        return Application(
            [
                (r"/gate-pass", _PassthroughGate),
                (r"/gate-parent-finished", _ParentFinishesEarly),
            ]
        )

    def test_passes_through_when_enabled(self):
        self._passthrough_cls.gate_enabled = True
        response = self.fetch("/gate-pass")
        assert response.code == 200
        assert json.loads(response.body) == {"ok": True}

    def test_short_circuits_when_disabled(self):
        self._passthrough_cls.gate_enabled = False
        response = self.fetch("/gate-pass")
        assert response.code == 403
        assert json.loads(response.body) == {"error": self.DISABLED_MESSAGE}

    def test_respects_parent_early_finish(self):
        response = self.fetch("/gate-parent-finished")
        assert response.code == 401
        assert json.loads(response.body) == {"error": "from parent"}


class TestPolicyGatedHandlerErrorMap:
    """Direct unit coverage for ``PolicyGatedHandler._error`` MRO walking.

    The mixin sorts mapped exception classes by MRO depth so a narrower
    subclass wins over its base. This was previously only exercised
    transitively by the skills handler tests; pin it directly so a
    regression in the sort key surfaces here.
    """

    def _stub_handler(self, exception_status_map):
        from notebook_intelligence.extension import PolicyGatedHandler

        handler = MagicMock(spec=PolicyGatedHandler)
        handler.exception_status_map = exception_status_map
        captured: dict = {}

        def _finish(payload):
            captured["body"] = payload

        handler.set_status.side_effect = lambda code: captured.setdefault(
            "status", code
        )
        handler.finish.side_effect = _finish
        return handler, captured

    def test_most_specific_class_wins_via_mro_depth(self):
        from notebook_intelligence.extension import PolicyGatedHandler

        handler, captured = self._stub_handler(
            {OSError: 500, FileNotFoundError: 404}
        )
        PolicyGatedHandler._error(handler, FileNotFoundError("missing"))
        assert captured["status"] == 404

    def test_unmapped_exception_falls_back_to_400(self):
        from notebook_intelligence.extension import PolicyGatedHandler

        handler, captured = self._stub_handler({FileNotFoundError: 404})
        PolicyGatedHandler._error(handler, RuntimeError("oops"))
        assert captured["status"] == 400
        assert json.loads(captured["body"]) == {"error": "oops"}

    def test_subclass_extends_inherited_map(self):
        from notebook_intelligence.extension import PolicyGatedHandler

        # Mimics a handler that adds KeyError to an inherited
        # PermissionError mapping. Each entry must be honored.
        handler, captured = self._stub_handler(
            {PermissionError: 403, KeyError: 422}
        )
        PolicyGatedHandler._error(handler, KeyError("k"))
        assert captured["status"] == 422

        handler, captured = self._stub_handler(
            {PermissionError: 403, KeyError: 422}
        )
        PolicyGatedHandler._error(handler, PermissionError("nope"))
        assert captured["status"] == 403


class TestPolicyGatedHandlerSubclassGuard:
    """The mixin's `__init_subclass__` refuses concrete subclasses that
    forget to declare `policy_enabled_attr` — force-off must fail closed,
    so a silent bypass would be a security regression worth catching at
    import time."""

    def test_concrete_subclass_without_attr_raises(self):
        from notebook_intelligence.extension import PolicyGatedHandler

        with pytest.raises(TypeError, match="policy_enabled_attr"):
            # NOTE: not suffixed BaseHandler — should error.
            class _Forgotten(PolicyGatedHandler):
                pass

    def test_intermediate_base_class_is_allowed_to_defer(self):
        from notebook_intelligence.extension import PolicyGatedHandler

        # An intermediate *BaseHandler can defer; concrete subclasses must
        # still set the attribute themselves (or inherit it).
        class _IntermediateBaseHandler(PolicyGatedHandler):
            pass

        with pytest.raises(TypeError, match="policy_enabled_attr"):
            class _ConcreteChild(_IntermediateBaseHandler):
                pass

        class _AnotherBaseHandler(PolicyGatedHandler):
            policy_enabled_attr = "something_enabled"

        # OK: concrete subclass inherits the attribute.
        class _ConcreteOK(_AnotherBaseHandler):
            pass

        assert _ConcreteOK.policy_enabled_attr == "something_enabled"
