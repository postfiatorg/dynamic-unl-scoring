from unittest.mock import MagicMock, patch

import pytest

from scripts import query


def _mock_response(content="ok"):
    message = MagicMock()
    message.content = content
    message.reasoning_content = None
    message.reasoning = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    usage = MagicMock()
    usage.prompt_tokens = 1
    usage.completion_tokens = 2
    usage.total_tokens = 3
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


@patch("scripts.query.OpenAI")
def test_create_client_omits_modal_proxy_headers_when_unset(mock_openai, monkeypatch):
    monkeypatch.delenv("MODAL_KEY", raising=False)
    monkeypatch.delenv("MODAL_SECRET", raising=False)

    query.create_client("https://example.modal.run/v1", timeout=10, env_file=None)

    mock_openai.assert_called_once_with(
        base_url="https://example.modal.run/v1",
        api_key="not-needed",
        timeout=10,
    )


@patch("scripts.query.OpenAI")
def test_create_client_sends_modal_proxy_headers_when_configured(
    mock_openai, monkeypatch
):
    monkeypatch.setenv("MODAL_KEY", " modal-key ")
    monkeypatch.setenv("MODAL_SECRET", " modal-secret ")

    query.create_client("https://example.modal.run/v1", timeout=10, env_file=None)

    mock_openai.assert_called_once_with(
        base_url="https://example.modal.run/v1",
        api_key="not-needed",
        default_headers={
            "Modal-Key": "modal-key",
            "Modal-Secret": "modal-secret",
        },
        timeout=10,
    )


@pytest.mark.parametrize(
    ("modal_key", "modal_secret"),
    [
        ("modal-key", ""),
        ("", "modal-secret"),
    ],
)
@patch("scripts.query.OpenAI")
def test_create_client_rejects_partial_modal_proxy_credentials(
    mock_openai, monkeypatch, modal_key, modal_secret
):
    monkeypatch.setenv("MODAL_KEY", modal_key)
    monkeypatch.setenv("MODAL_SECRET", modal_secret)

    with pytest.raises(ValueError, match="MODAL_KEY and MODAL_SECRET must be set together"):
        query.create_client("https://example.modal.run/v1", timeout=10, env_file=None)

    mock_openai.assert_not_called()


def test_load_local_env_reads_modal_proxy_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("MODAL_KEY", raising=False)
    monkeypatch.delenv("MODAL_SECRET", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MODAL_KEY=modal-key\nMODAL_SECRET=modal-secret\n")

    try:
        query._load_local_env(env_file)

        assert query.os.environ["MODAL_KEY"] == "modal-key"
        assert query.os.environ["MODAL_SECRET"] == "modal-secret"
    finally:
        query.os.environ.pop("MODAL_KEY", None)
        query.os.environ.pop("MODAL_SECRET", None)


def test_query_disables_qwen_thinking_by_default():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response()

    query.query(client, "test-model", [{"role": "user", "content": "hello"}])

    request_kwargs = client.chat.completions.create.call_args.kwargs
    assert request_kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_query_omits_non_thinking_override_when_thinking_enabled():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response()

    query.query(
        client,
        "test-model",
        [{"role": "user", "content": "hello"}],
        enable_thinking=True,
    )

    request_kwargs = client.chat.completions.create.call_args.kwargs
    assert "extra_body" not in request_kwargs


@patch("scripts.query.OpenAI")
def test_create_client_loads_modal_proxy_credentials_from_env_file(
    mock_openai, tmp_path, monkeypatch
):
    monkeypatch.delenv("MODAL_KEY", raising=False)
    monkeypatch.delenv("MODAL_SECRET", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MODAL_KEY=modal-key\nMODAL_SECRET=modal-secret\n")

    try:
        query.create_client("https://example.modal.run/v1", timeout=10, env_file=env_file)

        mock_openai.assert_called_once_with(
            base_url="https://example.modal.run/v1",
            api_key="not-needed",
            default_headers={
                "Modal-Key": "modal-key",
                "Modal-Secret": "modal-secret",
            },
            timeout=10,
        )
    finally:
        query.os.environ.pop("MODAL_KEY", None)
        query.os.environ.pop("MODAL_SECRET", None)
