"""Tests for audit log proctitle normalization and ausearch parsing."""

from __future__ import annotations

import unittest

from app.docker_quota.audit_parser import (
    extract_docker_subcommand,
    normalize_audit_proctitle,
    parse_ausearch_stdout,
    parse_execve_audit_line,
)


class TestNormalizeAuditProctitle(unittest.TestCase):
    def test_hex_docker_restart_binrev(self) -> None:
        h = "646F636B657200726573746172740062696E726576"
        self.assertEqual(
            normalize_audit_proctitle(h),
            "docker restart binrev",
        )

    def test_plaintext_unchanged(self) -> None:
        self.assertEqual(
            normalize_audit_proctitle("docker load -i pg15.tar.gz"),
            "docker load -i pg15.tar.gz",
        )

    def test_non_docker_hex_returns_raw(self) -> None:
        # "bash" in hex — not a docker argv blob we care about
        raw = "62617368002D6300"
        self.assertEqual(normalize_audit_proctitle(raw), raw)


class TestParseExecveLine(unittest.TestCase):
    def test_parses_quoted_argv(self) -> None:
        line = (
            'type=EXECVE msg=audit(1.0:1): argc=3 a0="docker" a1="restart" a2="binrev"'
        )
        argc, argv = parse_execve_audit_line(line)
        self.assertEqual(argc, 3)
        self.assertEqual(argv, ["docker", "restart", "binrev"])


class TestParseAusearchStdout(unittest.TestCase):
    def test_binrev_hex_log_block(self) -> None:
        block = """----
type=PROCTITLE msg=audit(1774339654.295:1028968): proctitle=646F636B657200726573746172740062696E726576
type=SYSCALL msg=audit(1774339654.295:1028968): arch=c000003e syscall=59 success=yes exit=0 pid=2201203 auid=1044 uid=1044 gid=1044 euid=1044 key="docker-client" comm="docker" exe="/usr/bin/docker"
----
"""
        events = parse_ausearch_stdout(block)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.get("uid"), 1044)
        self.assertEqual(ev.get("docker_subcommand"), "restart")
        self.assertEqual(ev.get("proctitle"), "docker restart binrev")
        self.assertAlmostEqual(ev.get("timestamp_unix", 0.0), 1774339654.295)

    def test_truncated_proctitle_execve_merges_full_cmdline(self) -> None:
        """Kernel hex proctitle is short; EXECVE has full ``docker run ... --name binrev``."""
        block = r"""----
time->Tue Mar 24 16:06:22 2026
type=PROCTITLE msg=audit(1774339582.741:1028819): proctitle=646F636B65720072756E002D64002D6974002D2D726573746172743D616C77617973002D2D6E6574776F726B3D686F7374002D2D6770757300616C6C002D76002F64617461332F6A616D302F43494D3A2F6D6F64656C732F43494D3A726F002D76002F64617461332F6A616D302F636F64656C6C616D613A2F6D6F64656C732F
type=CWD msg=audit(1774339582.741:1028819): cwd="/data3/jam0"
type=EXECVE msg=audit(1774339582.741:1028819): argc=22 a0="docker" a1="run" a2="-d" a3="-it" a4="--restart=always" a5="--network=host" a6="--gpus" a7="all" a8="-v" a9="/data3/jam0/CIM:/models/CIM:ro" a10="-v" a11="/data3/jam0/codellama:/models/symgen:ro" a12="-v" a13="/data3/jam0/Resym:/models/resym:ro" a14="-v" a15="/data3/jam0/binrev:/script:ro" a16="-v" a17="/data3/binllm:/workspace" a18="--name" a19="binrev" a20="binrev:v1" a21="/bin/bash"
type=SYSCALL msg=audit(1774339582.741:1028819): arch=c000003e syscall=59 success=yes exit=0 pid=2199816 auid=1044 uid=1044 gid=1044 euid=1044 key="docker-client" comm="docker" exe="/usr/bin/docker"
----
"""
        events = parse_ausearch_stdout(block)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.get("audit_time_text"), "Tue Mar 24 16:06:22 2026")
        self.assertEqual(ev.get("cwd"), "/data3/jam0")
        self.assertEqual(ev.get("execve_argc"), 22)
        self.assertEqual(ev.get("execve_argv", [])[19], "binrev")
        self.assertEqual(ev.get("docker_subcommand"), "run")
        self.assertEqual(ev.get("proctitle_source"), "execve")
        self.assertIn("--name", ev.get("proctitle") or "")
        self.assertIn("binrev:v1", ev.get("proctitle") or "")
        self.assertIn("binrev", ev.get("execve_cmdline") or "")


class TestExtractDockerSubcommand(unittest.TestCase):
    def test_run_with_name_binrev(self) -> None:
        pt = (
            "docker run -d -it --name binrev binrev:v1 /bin/bash"
        )
        self.assertEqual(extract_docker_subcommand(pt), "run")
