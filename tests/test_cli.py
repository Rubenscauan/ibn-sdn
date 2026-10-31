import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def invoke(*args):
    return subprocess.run([sys.executable, "-m", "ibn_sdn", *args], cwd=ROOT,
                          capture_output=True, text=True, check=False)


def test_demo_runs_all_scenarios_without_loading_rasa():
    result = invoke("--demo")
    assert result.returncode == 0, result.stderr
    decisions = [json.loads(line)["decision"] for line in result.stdout.splitlines()]
    assert [item["code"] for item in decisions] == [
        "HOST_PROTECTED", "APPLIED_TO_SIMULATION", "INSUFFICIENT_CAPACITY",
        "NO_PATH", "APPLIED_TO_SIMULATION", "EXISTING_BLOCK",
    ]


def test_dry_run_does_not_reserve_bandwidth_between_commands():
    result = invoke("--demo", "--dry-run")
    assert result.returncode == 0, result.stderr
    decisions = [json.loads(line)["decision"] for line in result.stdout.splitlines()]
    assert decisions[1]["status"] == decisions[2]["status"] == "APPROVED"


def test_cli_explains_missing_model_and_invalid_json(tmp_path):
    result = invoke("--text", "")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    result = invoke("--text", "bloqueie o host A", "--rasa-model", str(tmp_path / "missing.tar.gz"))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    result = invoke("--commands", str(tmp_path / "missing.json"))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
