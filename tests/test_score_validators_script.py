from scripts import score_validators


def test_parse_args_defaults_to_non_thinking(monkeypatch):
    monkeypatch.setattr(
        score_validators.sys,
        "argv",
        [
            "score_validators.py",
            "--url",
            "https://example.modal.run/v1",
        ],
    )

    args = score_validators.parse_args()

    assert args.enable_thinking is False


def test_parse_args_enables_thinking_when_requested(monkeypatch):
    monkeypatch.setattr(
        score_validators.sys,
        "argv",
        [
            "score_validators.py",
            "--url",
            "https://example.modal.run/v1",
            "--enable-thinking",
        ],
    )

    args = score_validators.parse_args()

    assert args.enable_thinking is True

