"""Phase 9.1: Helm chart sanity tests (no real kubectl/helm required).

These verify the chart files exist, parse as YAML, and reference each
other consistently. A full ``helm template`` round-trip happens in
CI on a different runner with helm installed; here we keep the test
suite Python-only.
"""
import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with pytest deps
    pytest.skip("PyYAML not available", allow_module_level=True)


_CHART_DIR = (
    Path(__file__).resolve().parents[3] / "k8s" / "helm" / "autocontrol"
)


def _yaml(path: str) -> dict:
    return yaml.safe_load((_CHART_DIR / path).read_text(encoding="utf-8"))


def _yaml_documents(path: str) -> list:
    raw = (_CHART_DIR / path).read_text(encoding="utf-8")
    return list(yaml.safe_load_all(raw))


# --- chart metadata --------------------------------------------------

def test_chart_yaml_has_required_fields():
    chart = _yaml("Chart.yaml")
    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "autocontrol"
    assert chart["type"] == "application"
    assert "version" in chart
    assert "appVersion" in chart


def test_values_yaml_declares_three_services():
    values = _yaml("values.yaml")
    for key in ("rest", "remoteHost", "signaling"):
        assert key in values, f"values.yaml missing {key} section"
        assert values[key]["enabled"] is True
        assert isinstance(values[key]["port"], int)


def test_values_yaml_empty_token_default():
    """The token must default to empty so the install fails fast without one."""
    values = _yaml("values.yaml")
    assert values["auth"]["token"] == ""


def test_values_yaml_resources_request_limits():
    values = _yaml("values.yaml")
    res = values["resources"]
    assert "requests" in res
    assert "limits" in res
    assert res["requests"]["cpu"] == "200m"


# --- template wiring ------------------------------------------------

def test_every_deployment_template_exists():
    for name in (
        "deployment-rest.yaml",
        "deployment-remote-host.yaml",
        "deployment-signaling.yaml",
    ):
        assert (_CHART_DIR / "templates" / name).exists(), \
            f"missing template: {name}"


def test_services_template_has_three_service_blocks():
    """PyYAML can't parse Helm conditionals — assert on the text instead."""
    raw = (_CHART_DIR / "templates" / "services.yaml").read_text(
        encoding="utf-8",
    )
    assert raw.count("kind: Service") == 3


def test_secret_template_references_auth_token():
    raw = (_CHART_DIR / "templates" / "secret.yaml").read_text(
        encoding="utf-8",
    )
    assert "Values.auth.token" in raw
    assert "AC_TOKEN" in raw  # the env var the entrypoint reads


def test_each_deployment_references_the_shared_secret():
    for name in (
        "deployment-rest.yaml",
        "deployment-remote-host.yaml",
    ):
        raw = (_CHART_DIR / "templates" / name).read_text(
            encoding="utf-8",
        )
        # The shared secret is the only place AC_TOKEN comes from.
        assert "secretKeyRef" in raw, f"{name} missing secretKeyRef"
        assert "AC_TOKEN" in raw, f"{name} missing AC_TOKEN env"


def test_helpers_define_label_macros():
    raw = (_CHART_DIR / "templates" / "_helpers.tpl").read_text(
        encoding="utf-8",
    )
    for macro in (
        "autocontrol.labels", "autocontrol.selectorLabels",
        "autocontrol.fullname", "autocontrol.requireToken",
    ):
        assert macro in raw, f"helper template missing {macro}"


def test_ingress_template_uses_rest_service_port_name():
    raw = (_CHART_DIR / "templates" / "ingress.yaml").read_text(
        encoding="utf-8",
    )
    # The ingress should target the named ``http`` port on the rest
    # service — not a hardcoded 9939 — so port overrides cascade.
    assert "port:\n                  name: http" in raw


def test_deployments_use_xvfb_geometry_value():
    """Every deployment must propagate the Xvfb geometry from values.yaml."""
    for name in (
        "deployment-rest.yaml",
        "deployment-remote-host.yaml",
        "deployment-signaling.yaml",
    ):
        raw = (_CHART_DIR / "templates" / name).read_text(
            encoding="utf-8",
        )
        assert "XVFB_GEOMETRY" in raw, f"{name} missing XVFB_GEOMETRY env"


def test_deployments_args_match_entrypoint_modes():
    """Each Deployment.args must be a mode the docker entrypoint knows."""
    expected = {
        "deployment-rest.yaml": "rest",
        "deployment-remote-host.yaml": "remote-host",
        "deployment-signaling.yaml": "signaling",
    }
    for filename, mode in expected.items():
        raw = (_CHART_DIR / "templates" / filename).read_text(
            encoding="utf-8",
        )
        assert f'args: ["{mode}"]' in raw, \
            f"{filename} should pass [{mode}] to the entrypoint"


# --- the chosen port reaches the program (D05) ----------------------

_VALUE_REF = re.compile(r"\{\{\s*\.Values\.([\w.]+)\s*(\|\s*quote\s*)?\}\}")


def _render_values(raw: str, values: dict) -> str:
    """Substitute the plain ``.Values`` references; leave other actions alone."""
    def _lookup(match: re.Match) -> str:
        value = values
        for key in match.group(1).split("."):
            value = value[key]
        return f'"{value}"' if match.group(2) else str(value)
    return _VALUE_REF.sub(_lookup, raw)


@pytest.mark.parametrize("filename,section", [
    ("deployment-rest.yaml", "rest"),
    ("deployment-remote-host.yaml", "remoteHost"),
    ("deployment-signaling.yaml", "signaling"),
])
def test_deployment_passes_its_port_to_the_program(filename, section):
    """A custom port moves the Service, the container port and the listener.

    The entrypoint reads the listen port from ``AC_PORT`` in every mode; a
    Deployment that only sets ``containerPort`` points the Service at a port
    nothing listens on.
    """
    values = _yaml("values.yaml")
    values[section]["port"] = 18000
    raw = _render_values(
        (_CHART_DIR / "templates" / filename).read_text(encoding="utf-8"), values)
    assert "containerPort: 18000" in raw
    assert re.search(r'- name: AC_PORT\n\s+value: "18000"\n', raw), \
        f"{filename} does not pass {section}.port to the program as AC_PORT"
