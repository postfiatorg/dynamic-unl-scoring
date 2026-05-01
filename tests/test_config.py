from scoring_service.config import QWEN_NON_THINKING_EXTRA_BODY, Settings


def test_scoring_defaults_use_qwen36_contract():
    settings = Settings(_env_file=None)

    assert settings.scoring_model_id == "Qwen/Qwen3.6-27B-FP8"
    assert settings.scoring_model_name == "qwen36-27b-fp8"
    assert settings.scoring_disable_thinking is True
    assert QWEN_NON_THINKING_EXTRA_BODY == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
