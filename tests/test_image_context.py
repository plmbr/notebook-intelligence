"""Tests for image/screenshot context handling in the chat websocket handler.

Covers the backend image branch added to WebsocketCopilotHandler.on_message:
- Valid image produces an OpenAI vision multimodal content block
- The base64 payload round-trips to the original bytes
- The mimeType field is reflected in the data URL prefix
- A missing file logs a warning and produces no chat history entry
- Non-image uploads still use the existing text file-path hint
- Mixed image + text context items both appear in history
"""

import asyncio
import base64
from contextlib import nullcontext
import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

from tornado.httputil import HTTPServerRequest
from tornado.web import Application

import notebook_intelligence.extension as ext_module
from notebook_intelligence.extension import WebsocketCopilotHandler


CHAT_ID = "test-chat"
USER_ID = "test-user"


def _scoped_chat_key(chat_id=CHAT_ID, user_id=USER_ID):
    return ext_module.ChatHistory._scope_key(chat_id, user_id=user_id)


def _make_handler():
    ext_module.shared_chat_history = ext_module.ChatHistory()
    WebsocketCopilotHandler.chat_history_ref = ext_module.shared_chat_history
    app = Mock(spec=Application)
    # JupyterHandler.set_default_headers reads application.settings and
    # the ui_* maps during __init__; provide enough for the mock to
    # satisfy that path without a real tornado application.
    app.settings = {"jinja2_env": None, "headers": {}}
    app.ui_methods = {}
    app.ui_modules = {}
    app.transforms = []
    request = Mock(spec=HTTPServerRequest)
    request.connection = Mock()
    with patch("notebook_intelligence.extension.ThreadSafeWebSocketConnector"):
        handler = WebsocketCopilotHandler(app, request)
    handler._jupyter_current_user = USER_ID
    # get_history() returns a throwaway list for unknown chat IDs; pre-seed so
    # messages appended by on_message are visible after the call returns.
    handler.chat_history.messages[_scoped_chat_key()] = []
    return handler


def _on_message(handler, additional_context, prompt="hello"):
    msg = json.dumps({
        "id": "msg-id",
        "type": "chat-request",
        "data": {
            "chatId": CHAT_ID,
            "prompt": prompt,
            "language": "python",
            "filename": "test.ipynb",
            "chatMode": "ask",
            "toolSelections": {},
            "additionalContext": additional_context,
        }
    })
    upload_paths = [
        Path(c["filePath"]) for c in additional_context if c.get("isUpload")
    ]
    upload_dir_patch = (
        patch(
            "notebook_intelligence.extension._upload_dir",
            str(upload_paths[0].parent),
        )
        if upload_paths
        else nullcontext()
    )
    with upload_dir_patch:
        asyncio.run(handler.on_message(msg))
    call = ext_module.ai_service_manager.handle_chat_request.call_args
    if call is None:
        return handler.chat_history.messages[_scoped_chat_key()]
    request = call.args[0]
    return list(request.chat_history) + [{"role": "user", "content": prompt}]

def _image_context(file_path, mime_type="image/png"):
    return {
        "isUpload": True,
        "isImage": True,
        "mimeType": mime_type,
        "filePath": str(file_path),
        "content": "",
        "currentCellContents": None,
        "startLine": 1,
        "endLine": 0,
    }


def _text_context(file_path, content, start=1, end=1):
    return {
        "isUpload": False,
        "isImage": False,
        "filePath": str(file_path),
        "content": content,
        "currentCellContents": None,
        "startLine": start,
        "endLine": end,
    }


@patch("notebook_intelligence.extension.ai_service_manager")
@patch("notebook_intelligence.extension.NotebookIntelligence")
@patch("notebook_intelligence.extension.threading.Thread")
class TestImageContextInChatHistory:

    def test_image_produces_multimodal_message(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(image_bytes)

        handler = _make_handler()
        history = _on_message(handler, [_image_context(img_file)])

        assert len(history) == 2
        image_msg = history[0]
        assert image_msg["role"] == "user"
        content = image_msg["content"]
        assert isinstance(content, list), "Image message content should be a list (multimodal)"
        assert content[0] == {
            "type": "text",
            "text": "The user pasted an image 'screenshot.png':",
        }
        assert content[1]["type"] == "image_url"

    def test_base64_payload_round_trips(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\xde\xad\xbe\xef" * 8
        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(image_bytes)

        handler = _make_handler()
        history = _on_message(handler, [_image_context(img_file)])

        url = history[0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        decoded = base64.b64decode(url.split(",", 1)[1])
        assert decoded == image_bytes

    def test_mime_type_reflected_in_data_url(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        img_file = tmp_path / "photo.jpg"
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)

        handler = _make_handler()
        history = _on_message(handler, [_image_context(img_file, mime_type="image/jpeg")])

        url = history[0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_missing_file_logs_warning_and_skips_entry(self, _thread, mock_nbi, mock_ai, tmp_path, caplog):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        missing = tmp_path / "does_not_exist.png"

        handler = _make_handler()
        with caplog.at_level(logging.WARNING, logger="notebook_intelligence.extension"):
            history = _on_message(handler, [_image_context(missing)])

        assert len(history) == 1
        assert history[0] == {"role": "user", "content": "hello"}
        assert any("does_not_exist.png" in r.message for r in caplog.records)

    def test_non_image_upload_uses_text_hint(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        handler = _make_handler()
        binary_upload = {
            "isUpload": True,
            "isImage": False,
            "filePath": "/tmp/nbi-uploads/uuid/report.pdf",
            "content": "",
            "currentCellContents": None,
            "startLine": 1,
            "endLine": 0,
        }
        history = _on_message(handler, [binary_upload])

        text_msg = history[0]
        assert isinstance(text_msg["content"], str), "Non-image upload should produce a plain-text message"
        assert "report.pdf" in text_msg["content"]
        assert "Read this file" in text_msg["content"]

    def test_mixed_image_and_text_context(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        img_file = tmp_path / "shot.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        handler = _make_handler()
        history = _on_message(handler, [
            _image_context(img_file),
            _text_context("script.py", "print('hello')"),
        ], prompt="what does this do?")

        assert len(history) == 3
        assert isinstance(history[0]["content"], list)
        assert isinstance(history[1]["content"], str)
        assert history[2]["content"] == "what does this do?"

    def test_image_context_not_charged_against_token_budget(self, _thread, mock_nbi, mock_ai, tmp_path):
        """Image items should not consume the token budget, leaving room for text context."""
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        img_file = tmp_path / "shot.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        handler = _make_handler()
        history = _on_message(handler, [
            _image_context(img_file),
            _text_context("tiny.py", "x = 1"),
        ])

        assert len(history) == 3

    def test_claude_code_mode_sends_file_path_not_base64(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = True

        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        handler = _make_handler()
        history = _on_message(handler, [_image_context(img_file)])

        image_msg = history[0]
        assert isinstance(image_msg["content"], str), "Claude Code mode should send plain text, not multimodal list"
        assert str(img_file) in image_msg["content"]
        assert "base64" not in image_msg["content"]

    def test_claude_code_mode_missing_file_still_adds_path_message(self, _thread, mock_nbi, mock_ai, tmp_path):
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = True

        missing = tmp_path / "does_not_exist.png"

        handler = _make_handler()
        history = _on_message(handler, [_image_context(missing)])

        # Claude Code mode passes the path without reading the file, so no error even if missing
        image_msg = history[0]
        assert isinstance(image_msg["content"], str)
        assert str(missing) in image_msg["content"]

    def test_workspace_image_drag_reaches_vision_provider(
        self, _thread, mock_nbi, mock_ai, tmp_path
    ):
        # File-browser drag of an image sets isImage=true and isUpload=false
        # (no temp staging); the backend should still send the multimodal
        # vision payload so OpenAI-vision providers see the image bytes.
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\xfe\xed\xfa\xce" * 8
        img_file = tmp_path / "diagram.png"
        img_file.write_bytes(image_bytes)

        ctx = _image_context(img_file)
        ctx["isUpload"] = False
        ctx["filePath"] = "diagram.png"  # workspace-relative, as the
                                         # frontend file-browser handler sends.

        handler = _make_handler()
        history = _on_message(handler, [ctx])

        image_msg = history[0]
        assert isinstance(image_msg["content"], list)
        assert image_msg["content"][1]["type"] == "image_url"
        b64 = image_msg["content"][1]["image_url"]["url"].split(",", 1)[1]
        assert base64.b64decode(b64) == image_bytes

    def test_image_context_is_request_scoped_not_persisted_in_shared_history(
        self, _thread, mock_nbi, mock_ai, tmp_path
    ):
        """Image context should affect only the current request payload.

        It must not be persisted into shared ``self.chat_history`` across
        turns; otherwise a later request without image attachments would
        silently inherit old image context.
        """
        mock_nbi.root_dir = str(tmp_path)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        img_file = tmp_path / "shot.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        handler = _make_handler()

        first_history = _on_message(handler, [_image_context(img_file)], prompt="first turn")
        assert len(first_history) == 2
        assert isinstance(first_history[0]["content"], list)
        assert first_history[-1]["content"] == "first turn"

        second_history = _on_message(handler, [], prompt="second turn")
        assert second_history[-1]["content"] == "second turn"
        # Previous image context should not leak into a later request.
        assert not any(isinstance(item.get("content"), list) for item in second_history)
        # Shared persisted history should keep user prompts only.
        persisted = handler.chat_history.messages[_scoped_chat_key()]
        assert [m["content"] for m in persisted] == ["first turn", "second turn"]

    def test_path_traversal_outside_workspace_is_rejected(
        self, _thread, mock_nbi, mock_ai, tmp_path, caplog
    ):
        # A workspace-relative path that escapes via ``..`` must not read
        # from outside root_dir. Create a sentinel file outside the
        # workspace and try to attach it.
        outside = tmp_path.parent / "secret.txt"
        outside.write_bytes(b"do-not-read")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        mock_nbi.root_dir = str(workspace)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        ctx = {
            "isUpload": False,
            "isImage": False,
            "filePath": "../secret.txt",
            "content": "do-not-read",  # client-provided body is ignored
                                       # once the path check rejects.
            "currentCellContents": None,
            "startLine": 1,
            "endLine": 1,
        }

        handler = _make_handler()
        with caplog.at_level(logging.WARNING):
            history = _on_message(handler, [ctx])

        # Only the user prompt remains; the traversal context was dropped.
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert "Rejecting out-of-workspace context path" in caplog.text

    def test_absolute_path_outside_workspace_is_rejected(
        self, _thread, mock_nbi, mock_ai, tmp_path, caplog
    ):
        # path.join silently returns the absolute path when the second
        # arg is absolute, so a malformed payload could pass an absolute
        # ``/etc/passwd`` without escaping ``root_dir``. Sandbox catches it.
        outside = tmp_path.parent / "absolute-secret.txt"
        outside.write_bytes(b"do-not-read")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        mock_nbi.root_dir = str(workspace)
        mock_ai.chat_model = None
        mock_ai.is_claude_code_mode = False

        ctx = {
            "isUpload": False,
            "isImage": False,
            "filePath": str(outside),
            "content": "do-not-read",
            "currentCellContents": None,
            "startLine": 1,
            "endLine": 1,
        }

        handler = _make_handler()
        with caplog.at_level(logging.WARNING):
            history = _on_message(handler, [ctx])

        assert len(history) == 1
        assert "Rejecting out-of-workspace context path" in caplog.text
