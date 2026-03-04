from executor.templates import SandboxTemplate, TemplateManager


def test_get_sandbox_kwargs_for_known_template():
    manager = TemplateManager()
    kwargs = manager.get_sandbox_kwargs("node-basic")

    assert kwargs["image"] == "node:18-slim"
    assert kwargs["memory_limit"] == "512m"
    assert kwargs["cpu_quota"] == 100000
    assert kwargs["timeout"] == 30
    assert kwargs["network_disabled"] is True


def test_get_sandbox_kwargs_unknown_template_falls_back_to_default():
    manager = TemplateManager()
    kwargs = manager.get_sandbox_kwargs("does-not-exist")

    assert kwargs["image"] == "executor-sandbox:latest"
    assert kwargs["memory_limit"] == "512m"
    assert kwargs["cpu_quota"] == 100000


def test_validate_template_reports_invalid_fields():
    manager = TemplateManager()
    invalid = SandboxTemplate(
        name="",
        description="invalid",
        base_image="",
        memory_limit="0m",
        cpu_quota=0,
        timeout=0,
    )

    errors = manager.validate_template(invalid)

    assert "Template name is required" in errors
    assert "Base image is required" in errors
    assert "Memory limit must be greater than 0" in errors
    assert "CPU quota must be greater than 0" in errors
    assert "Timeout must be between 1 and 3600 seconds" in errors


def test_register_template_rejects_invalid_config():
    manager = TemplateManager()
    invalid = SandboxTemplate(
        name="bad-template",
        description="invalid",
        base_image="executor-sandbox:latest",
        memory_limit="0m",
        cpu_quota=100000,
        timeout=30,
    )

    assert manager.register_template(invalid) is False
    assert manager.get_template("bad-template") is None


def test_register_and_unregister_custom_template():
    manager = TemplateManager()
    custom = SandboxTemplate(
        name="custom-python",
        description="custom",
        base_image="executor-sandbox:latest",
        memory_limit="512m",
        cpu_quota=100000,
        timeout=30,
    )

    assert manager.register_template(custom) is True
    assert manager.get_template("custom-python") is not None
    assert manager.unregister_template("custom-python") is True
    assert manager.get_template("custom-python") is None
