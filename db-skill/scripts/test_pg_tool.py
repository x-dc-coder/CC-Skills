#!/usr/bin/env python3
"""Test suite for pg_tool.py."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add script directory to path
sys.path.insert(0, str(Path(__file__).parent))

import pg_tool as pg


class TestResolveConfigPath(unittest.TestCase):
    def test_explicit_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"pg": {"user": "test"}}')
            path = f.name
        try:
            result = pg.resolve_config_path(path)
            self.assertEqual(result, Path(path).resolve())
        finally:
            os.unlink(path)

    def test_explicit_path_not_found(self):
        with self.assertRaises(FileNotFoundError):
            pg.resolve_config_path("/nonexistent/config.json")

    def test_env_var(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"pg": {"user": "test"}}')
            path = f.name
        old_env = os.environ.get("DB_SKILL_CONFIG")
        try:
            os.environ["DB_SKILL_CONFIG"] = path
            result = pg.resolve_config_path(None)
            self.assertEqual(result, Path(path).resolve())
        finally:
            if old_env is None:
                os.environ.pop("DB_SKILL_CONFIG", None)
            else:
                os.environ["DB_SKILL_CONFIG"] = old_env
            os.unlink(path)

    def test_env_var_not_found(self):
        old_env = os.environ.get("DB_SKILL_CONFIG")
        try:
            os.environ["DB_SKILL_CONFIG"] = "/nonexistent/config.json"
            with self.assertRaises(FileNotFoundError):
                pg.resolve_config_path(None)
        finally:
            if old_env is None:
                os.environ.pop("DB_SKILL_CONFIG", None)
            else:
                os.environ["DB_SKILL_CONFIG"] = old_env

    def test_auto_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".db-skill" / "pg.json"
            config_path.parent.mkdir()
            config_path.write_text('{"pg": {"user": "test"}}')
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                result = pg.resolve_config_path(None)
                self.assertEqual(result, config_path.resolve())
            finally:
                os.chdir(original_cwd)

    def test_auto_discovery_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with self.assertRaises(FileNotFoundError) as ctx:
                    pg.resolve_config_path(None)
                self.assertIn("No config file found", str(ctx.exception))
            finally:
                os.chdir(original_cwd)


class TestLoadConfig(unittest.TestCase):
    def test_valid_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"pg": {"user": "test"}, "limits": {"default_limit": 100}}, f)
            path = f.name
        try:
            cfg = pg.load_config(Path(path))
            self.assertIn("pg", cfg)
            self.assertEqual(cfg["limits"]["default_limit"], 100)
            self.assertEqual(cfg["limits"]["max_limit"], 1000)
        finally:
            os.unlink(path)

    def test_missing_pg_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"mysql": {"user": "test"}}, f)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                pg.load_config(Path(path))
            self.assertIn("'pg' object", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_limits_not_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"pg": {"user": "test"}, "limits": "invalid"}, f)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                pg.load_config(Path(path))
            self.assertIn("'limits' must be an object", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_default_limits(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"pg": {"user": "test"}}, f)
            path = f.name
        try:
            cfg = pg.load_config(Path(path))
            self.assertEqual(cfg["limits"]["default_limit"], 200)
            self.assertEqual(cfg["limits"]["max_limit"], 1000)
        finally:
            os.unlink(path)


class TestReadSql(unittest.TestCase):
    def test_sql_text(self):
        result = pg.read_sql("SELECT * FROM users", None)
        self.assertEqual(result, "SELECT * FROM users")

    def test_sql_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
            f.write("SELECT * FROM orders")
            path = f.name
        try:
            result = pg.read_sql(None, path)
            self.assertEqual(result, "SELECT * FROM orders")
        finally:
            os.unlink(path)

    def test_both_provided(self):
        with self.assertRaises(ValueError) as ctx:
            pg.read_sql("SELECT 1", "/tmp/test.sql")
        self.assertIn("exactly one", str(ctx.exception))

    def test_neither_provided(self):
        with self.assertRaises(ValueError) as ctx:
            pg.read_sql(None, None)
        self.assertIn("exactly one", str(ctx.exception))

    def test_empty_sql(self):
        with self.assertRaises(ValueError) as ctx:
            pg.read_sql("   ", None)
        self.assertIn("SQL is empty", str(ctx.exception))

    def test_trailing_semicolon_stripped(self):
        result = pg.read_sql("SELECT 1;", None)
        self.assertEqual(result, "SELECT 1")


class TestIsReadQuery(unittest.TestCase):
    def test_select(self):
        self.assertTrue(pg.is_read_query("SELECT * FROM users"))

    def test_with_cte(self):
        self.assertTrue(pg.is_read_query("WITH cte AS (SELECT 1) SELECT * FROM cte"))

    def test_insert(self):
        self.assertFalse(pg.is_read_query("INSERT INTO users (name) VALUES ('test')"))

    def test_update(self):
        self.assertFalse(pg.is_read_query("UPDATE users SET name = 'test'"))

    def test_delete(self):
        self.assertFalse(pg.is_read_query("DELETE FROM users WHERE id = 1"))

    def test_select_with_comment(self):
        self.assertTrue(pg.is_read_query("/* comment */ SELECT * FROM users"))

    def test_select_with_line_comment(self):
        self.assertTrue(pg.is_read_query("-- comment\nSELECT * FROM users"))

    def test_mixed_case(self):
        self.assertTrue(pg.is_read_query("select * from users"))
        self.assertTrue(pg.is_read_query("SELECT * FROM users"))


class TestBoundedSelectSql(unittest.TestCase):
    def test_wraps_query(self):
        result = pg.bounded_select_sql("SELECT * FROM users", 100)
        self.assertEqual(result, "SELECT * FROM (SELECT * FROM users) AS __db_skill_q LIMIT 100")


class TestChooseLimit(unittest.TestCase):
    def test_default(self):
        cfg = {"limits": {"default_limit": 200, "max_limit": 1000}}
        chosen, max_limit = pg.choose_limit(None, cfg)
        self.assertEqual(chosen, 200)
        self.assertEqual(max_limit, 1000)

    def test_user_specified(self):
        cfg = {"limits": {"default_limit": 200, "max_limit": 1000}}
        chosen, max_limit = pg.choose_limit(50, cfg)
        self.assertEqual(chosen, 50)

    def test_negative_clamped_to_1(self):
        cfg = {"limits": {"default_limit": 200, "max_limit": 1000}}
        chosen, _ = pg.choose_limit(-5, cfg)
        self.assertEqual(chosen, 1)

    def test_exceeds_max_clamped(self):
        cfg = {"limits": {"default_limit": 200, "max_limit": 1000}}
        chosen, _ = pg.choose_limit(5000, cfg)
        self.assertEqual(chosen, 1000)


class TestEnsureJsonable(unittest.TestCase):
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        self.assertEqual(pg.ensure_jsonable_value(dt), "2024-01-15T10:30:00")

    def test_date(self):
        d = date(2024, 1, 15)
        self.assertEqual(pg.ensure_jsonable_value(d), "2024-01-15")

    def test_decimal(self):
        self.assertEqual(pg.ensure_jsonable_value(Decimal("99.99")), 99.99)

    def test_bytes(self):
        self.assertEqual(pg.ensure_jsonable_value(b"hello"), "hello")

    def test_plain_string(self):
        self.assertEqual(pg.ensure_jsonable_value("hello"), "hello")

    def test_row(self):
        row = {
            "id": 1,
            "name": "test",
            "created_at": datetime(2024, 1, 1),
            "score": Decimal("95.5"),
        }
        result = pg.ensure_jsonable_row(row)
        self.assertEqual(result["created_at"], "2024-01-01T00:00:00")
        self.assertEqual(result["score"], 95.5)


class TestMakeOutputPath(unittest.TestCase):
    def test_temp_path(self):
        path = pg.make_output_path(None)
        self.assertTrue(path.exists())
        self.assertIn("pg-result-", path.name)
        self.assertEqual(path.suffix, ".json")
        path.unlink()

    def test_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pg.make_output_path(f"{tmpdir}/output.json")
            self.assertEqual(path, Path(tmpdir) / "output.json")
            self.assertFalse(path.exists())
            self.assertTrue(path.parent.exists())


class TestConnectPg(unittest.TestCase):
    def _mock_psycopg2(self):
        """Create a mock psycopg2 module with extras subpackage."""
        mock = MagicMock()
        mock.extras = MagicMock()
        mock.extras.RealDictCursor = MagicMock()
        return mock

    def test_connection_params(self):
        mock_psycopg2 = self._mock_psycopg2()
        mock_connect = mock_psycopg2.connect
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        with patch.dict(sys.modules, {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            pg_cfg = {
                "host": "127.0.0.1",
                "port": 5432,
                "user": "postgres",
                "password": "secret",
                "database": "testdb",
            }
            conn, driver = pg.connect_pg(pg_cfg)

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args.kwargs
            self.assertEqual(call_kwargs["host"], "127.0.0.1")
            self.assertEqual(call_kwargs["port"], 5432)
            self.assertEqual(call_kwargs["user"], "postgres")
            self.assertEqual(call_kwargs["password"], "secret")
            self.assertEqual(call_kwargs["dbname"], "testdb")
            self.assertEqual(call_kwargs["connect_timeout"], 5)
            self.assertFalse(conn.autocommit)
            self.assertEqual(driver, "psycopg2")

    def test_missing_host_uses_default(self):
        mock_psycopg2 = self._mock_psycopg2()
        mock_psycopg2.connect.return_value = MagicMock()
        with patch.dict(sys.modules, {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            pg.connect_pg({"user": "postgres", "password": "secret"})
            call_kwargs = mock_psycopg2.connect.call_args.kwargs
            self.assertEqual(call_kwargs["host"], "127.0.0.1")
            self.assertEqual(call_kwargs["port"], 5432)

    def test_connection_failure(self):
        mock_psycopg2 = self._mock_psycopg2()
        mock_psycopg2.connect.side_effect = Exception("Connection refused")
        with patch.dict(sys.modules, {"psycopg2": mock_psycopg2, "psycopg2.extras": mock_psycopg2.extras}):
            with self.assertRaises(RuntimeError) as ctx:
                pg.connect_pg({"user": "postgres"})
            self.assertIn("Cannot connect to PostgreSQL", str(ctx.exception))


class TestIntegrationWithRealDb(unittest.TestCase):
    """Integration tests using the real PostgreSQL service."""

    @classmethod
    def setUpClass(cls):
        cls.test_config_path = "/tmp/pg-test-config/.db-skill/pg.json"
        if not Path(cls.test_config_path).exists():
            raise unittest.SkipTest("Test config not found")

    def _run_pg_tool(self, args: list, cwd: str) -> subprocess.CompletedProcess:
        """Helper to run pg_tool.py as a subprocess in the given working directory."""
        cmd = [
            sys.executable,
            str(Path(__file__).parent / "pg_tool.py"),
            "run",
            "--config", self.test_config_path,
        ] + args
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

    def test_01_select_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "SELECT id, name, email FROM db_skill_test_users WHERE id <= 5 ORDER BY id",
                "--limit", "10",
                "--jq", ".data[].id",
                "--no-preview",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"ok": true', result.stdout)

    def test_02_select_with_limit_enforced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "SELECT id FROM db_skill_test_users",
                "--limit", "10",
                "--jq", ".data[].id",
                "--no-preview",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"rows": 10', result.stdout)
            self.assertIn('"limit_applied": 10', result.stdout)

    def test_03_default_limit_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "SELECT id FROM db_skill_test_users",
                "--no-preview",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            # config has default_limit: 50
            self.assertIn('"rows": 50', result.stdout)
            self.assertIn('"limit_applied": 50', result.stdout)

    def test_04_write_without_confirm_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "INSERT INTO db_skill_test_users (name) VALUES ('test')",
            ], tmpdir)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Non-read SQL requires explicit --confirm-write", result.stderr)

    def test_05_insert_with_confirm_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "INSERT INTO db_skill_test_users (name) VALUES ('integration_test_user')",
                "--confirm-write",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"ok": true', result.stdout)
            self.assertIn('"type": "exec"', result.stdout)
            self.assertIn('"affected_rows": 1', result.stdout)

    def test_06_sql_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sql_file = Path(tmpdir) / "query.sql"
            sql_file.write_text("SELECT COUNT(*) AS total FROM db_skill_test_users")
            result = self._run_pg_tool([
                "--sql-file", str(sql_file),
                "--no-preview",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"ok": true', result.stdout)
            self.assertIn('"type": "query"', result.stdout)

    def test_07_decimal_and_date_serialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "result.json"
            result = self._run_pg_tool([
                "--sql", "SELECT id, score, birth_date FROM db_skill_test_users WHERE id = 1",
                "--limit", "5",
                "--no-preview",
                "--output", str(output_file),
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            data = json.loads(output_file.read_text())
            row = data["data"][0]
            self.assertIn("score", row)
            self.assertIsInstance(row["score"], float)
            self.assertIn("birth_date", row)
            self.assertIsInstance(row["birth_date"], str)

    def test_08_jq_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "SELECT id, name FROM db_skill_test_users WHERE id <= 3 ORDER BY id",
                "--limit", "5",
                "--jq", ".data[].name",
            ], tmpdir)
            self.assertEqual(result.returncode, 0)
            self.assertIn('"preview_with_jq": true', result.stdout)
            self.assertIn("User 1", result.stdout)

    def test_09_rollback_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_pg_tool([
                "--sql", "SELECT * FROM nonexistent_table_xyz",
                "--no-preview",
            ], tmpdir)
            self.assertEqual(result.returncode, 1)
            self.assertIn('"ok": false', result.stderr)
            self.assertIn("nonexistent_table_xyz", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
