import json
from pathlib import Path

import yaml

from config_resolver.cli import EXIT_OK, EXIT_USAGE, main


class TestApplyCommand:
    FILE_CONFIG = """\
database:
  host: db.file
  port: 5432
  password: filesecret
  pool_size: 5
"""

    @staticmethod
    def _write_inputs(
        tmp_path: Path,
        env_spec: dict,
        files: dict[str, str] | None = None,
    ) -> Path:
        for name, content in (files or {}).items():
            (tmp_path / name).write_text(content)
        inputs_path = tmp_path / "sources.yaml"
        inputs_path.write_text(yaml.safe_dump({"environments": {"staging": env_spec}}))
        return inputs_path


    def test_dry_run_prints_merged_and_writes_nothing(self, tmp_path, capsys):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )
        out_file = tmp_path / "out.yaml"

        rc = main(
            ["--inputs", str(inputs), "apply", "staging", "--dry-run", "--output", str(out_file)]
        )

        assert rc == EXIT_OK
        stdout = capsys.readouterr().out
        assert "host: db.file" in stdout
        assert not out_file.exists()

    def test_dry_run_masks_secrets(self, tmp_path, capsys):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run"])

        assert rc == EXIT_OK
        stdout = capsys.readouterr().out
        assert "********" in stdout
        assert "filesecret" not in stdout

    def test_dry_run_json_format(self, tmp_path, capsys):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run", "--format", "json"])

        assert rc == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["database"]["host"] == "db.file"
        assert payload["database"]["password"] == "********"

    def test_apply_writes_unmasked_file(self, tmp_path):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )
        out_file = tmp_path / "nested" / "out.yaml"

        rc = main(["--inputs", str(inputs), "apply", "staging", "--output", str(out_file)])

        assert rc == EXIT_OK
        written = yaml.safe_load(out_file.read_text())
        assert written["database"]["password"] == "filesecret"
        assert written["database"]["host"] == "db.file"

    def test_apply_without_output_or_dry_run_is_usage_error(self, tmp_path):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )

        rc = main(["--inputs", str(inputs), "apply", "staging"])

        assert rc == EXIT_USAGE

    def test_unknown_environment_is_usage_error(self, tmp_path):
        inputs = self._write_inputs(
            tmp_path, {"file": "config.yaml"}, {"config.yaml": self.FILE_CONFIG}
        )

        rc = main(["--inputs", str(inputs), "apply", "does-not-exist", "--dry-run"])

        assert rc == EXIT_USAGE

    def test_env_overrides_file_by_default(self, tmp_path, capsys, monkeypatch):
        inputs = self._write_inputs(
            tmp_path,
            {"file": "config.yaml", "env_prefix": "APP_"},
            {"config.yaml": self.FILE_CONFIG},
        )
        monkeypatch.setenv("APP_DATABASE__HOST", "db.env")

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run"])

        assert rc == EXIT_OK
        merged = yaml.safe_load(capsys.readouterr().out)
        assert merged["database"]["host"] == "db.env"

    def test_custom_precedence_lets_file_win_over_env(self, tmp_path, capsys, monkeypatch):
        inputs = self._write_inputs(
            tmp_path,
            {"file": "config.yaml", "env_prefix": "APP_"},
            {"config.yaml": self.FILE_CONFIG},
        )
        monkeypatch.setenv("APP_DATABASE__HOST", "db.env")

        rc = main(
            ["--inputs", str(inputs), "apply", "staging", "--dry-run", "--precedence", "env,file"]
        )

        assert rc == EXIT_OK
        merged = yaml.safe_load(capsys.readouterr().out)
        assert merged["database"]["host"] == "db.file"

    def test_nested_env_vars_merge_without_clobbering_file(self, tmp_path, capsys, monkeypatch):
        inputs = self._write_inputs(
            tmp_path,
            {"file": "config.yaml", "env_prefix": "APP_"},
            {"config.yaml": self.FILE_CONFIG},
        )
        monkeypatch.setenv("APP_DATABASE__POOL_SIZE", "20")

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run"])

        assert rc == EXIT_OK
        merged = yaml.safe_load(capsys.readouterr().out)
        assert merged["database"]["pool_size"] == 20
        assert merged["database"]["host"] == "db.file"

    def test_missing_file_without_allow_partial_is_error(self, tmp_path):
        inputs = self._write_inputs(tmp_path, {"file": "missing.yaml"})

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run"])

        assert rc == EXIT_USAGE

    def test_missing_file_with_allow_partial_proceeds(self, tmp_path, capsys, monkeypatch):
        inputs = self._write_inputs(tmp_path, {"file": "missing.yaml", "env_prefix": "APP_"})
        monkeypatch.setenv("APP_DATABASE__HOST", "db.env")

        rc = main(["--inputs", str(inputs), "apply", "staging", "--dry-run", "--allow-partial"])

        assert rc == EXIT_OK
        merged = yaml.safe_load(capsys.readouterr().out)
        assert merged["database"]["host"] == "db.env"
