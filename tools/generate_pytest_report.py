#!/usr/bin/env python3
"""Pytest Pipeline Analyzer - Analyze pytest commands in CI pipeline YAML files and buildkite scripts."""

import os
import sys
import yaml
import subprocess
import glob
import fnmatch
import argparse
import csv
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class AnalysisResults:
    all_test_files: Set[str]
    covered_files: Set[str]
    orphan_files: Set[str]
    file_to_labels: Dict[str, List[str]]
    multiple_coverage: Dict[str, List[str]]
    single_coverage: Dict[str, List[str]]
    total_pytest_commands: int


class PytestPipelineAnalyzer:
    def __init__(
        self,
        yaml_file: str,
        tests_dir: str = "tests",
        working_dir: Optional[str] = None,
        buildkite_scripts_dir: Optional[str] = None,
    ):
        self.yaml_file = os.path.abspath(yaml_file)
        self.tests_dir = os.path.abspath(tests_dir)
        self.buildkite_scripts_dir = buildkite_scripts_dir

        if not os.path.exists(self.yaml_file):
            raise FileNotFoundError(f"YAML file not found: {self.yaml_file}")

        if working_dir:
            os.chdir(working_dir)

    def get_all_test_files(self) -> Set[str]:
        test_files = set()
        if not os.path.exists(self.tests_dir):
            return test_files

        try:
            result = subprocess.run(
                [
                    "find",
                    self.tests_dir,
                    "-name",
                    "test_*.py",
                    "-o",
                    "-name",
                    "*_test.py",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            for file_path in result.stdout.strip().split("\n"):
                if file_path:
                    test_files.add(os.path.relpath(file_path, self.tests_dir))
        except:
            for pattern in ["test_*.py", "*_test.py"]:
                for file_path in Path(self.tests_dir).rglob(pattern):
                    test_files.add(os.path.relpath(file_path, self.tests_dir))

        return test_files

    def extract_pytest_commands(
        self, yaml_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        commands = []

        for step in yaml_data.get("steps", []):
            if not isinstance(step, dict):
                continue

            label = step.get("label", "Unknown")
            step_commands = []

            if "command" in step:
                step_commands = [step["command"]]
            elif "commands" in step and isinstance(step["commands"], list):
                step_commands = step["commands"]

            for command in step_commands:
                command_str = (
                    " ".join(str(c) for c in command)
                    if isinstance(command, list)
                    else str(command)
                )
                command_str = command_str.strip()

                # Handle only test-related commands that execute files in tests/ directory
                if any(
                    keyword in command_str.lower()
                    for keyword in [
                        "pytest",
                        "python test",
                        "torchrun",
                    ]
                ):
                    # Handle pytest commands
                    if "pytest" in command_str:
                        parts = command_str.split()
                        for i, part in enumerate(parts):
                            if part == "pytest" or part.startswith("pytest"):
                                pytest_cmd = " ".join(parts[i:])
                                commands.append((label, pytest_cmd))
                                break
                    # Handle other test execution commands (only if they execute test files)
                    elif self._is_test_execution(command_str):
                        commands.append((label, command_str))

        return commands

    def parse_pytest_command(self, command: str) -> Tuple[List[str], List[str]]:
        parts = command.split()
        patterns = []
        ignore_flags = []

        # Handle different pytest invocation styles
        pytest_idx = -1
        for i, part in enumerate(parts):
            if (
                part == "pytest"
                or (
                    part == "python3"
                    and i + 2 < len(parts)
                    and parts[i + 2] == "pytest"
                )
                or (
                    part == "python" and i + 2 < len(parts) and parts[i + 2] == "pytest"
                )
            ):
                if part.startswith("python"):
                    pytest_idx = i + 2  # Skip "python3 -m pytest"
                else:
                    pytest_idx = i  # Direct pytest
                break

        if pytest_idx == -1:
            return patterns, ignore_flags

        i = pytest_idx + 1
        while i < len(parts):
            part = parts[i]

            if part.startswith("--ignore="):
                ignore_flags.append(part)
            elif part.startswith("--ignore"):
                if "=" not in part and i + 1 < len(parts):
                    ignore_flags.append(f"--ignore={parts[i + 1]}")
                    i += 1
                else:
                    ignore_flags.append(part)
            elif part.startswith("-"):
                # Handle all types of flags with optional arguments
                if part in [
                    "-k",
                    "--tb",
                    "--maxfail",
                    "--shard-id",
                    "--num-shards",
                    "-m",
                    "--durations",
                    "--lf",
                    "--ff",
                    "--cache-clear",
                    "--rootdir",
                    "--basetemp",
                    "--capture",
                    "--cov",
                    "--cov-report",
                    "--cov-fail-under",
                    "--junitxml",
                    "--resultlog",
                    "--pastebin",
                    "--pdb",
                    "--pdbcls",
                    "--trace",
                    "--profile",
                    "--benchmark-only",
                    "--benchmark-disable",
                    "--tb-short",
                    "--tb-long",
                    "--tb-no",
                    "--strict",
                    "--disable-warnings",
                ] and i + 1 < len(parts):
                    if not parts[i + 1].startswith("-"):
                        i += 1
                # Handle multi-value flags
                elif part in ["--cov-report"] and i + 1 < len(parts):
                    while i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                        i += 1
            else:
                # Normalize test file paths
                normalized_part = self._normalize_test_path(part)
                if normalized_part:
                    patterns.append(normalized_part)

            i += 1

        return patterns, ignore_flags

    def _normalize_test_path(self, path: str) -> str:
        """Normalize test paths to be relative to the tests directory."""
        # Clean up the path first - remove quotes and whitespace
        path = path.strip().strip('"').strip("'")

        # Handle absolute paths from buildkite scripts
        if path.startswith("/workspace/vllm/tests/"):
            path = path.replace("/workspace/vllm/tests/", "")
        elif path.startswith("tests/"):
            path = path.replace("tests/", "")
        elif path.startswith("./tests/"):
            path = path.replace("./tests/", "")
        elif "::" in path:
            # Handle specific test function calls like "test_file.py::test_function"
            test_file = path.split("::")[0]
            return self._normalize_test_path(test_file)

        return path

    def _is_test_execution(self, command: str) -> bool:
        """Check if a command is executing a test file in the tests/ directory."""
        command_lower = command.lower()

        # Only check for direct execution of test files in the tests/ directory
        if "test" in command_lower and ".py" in command_lower:
            # Check if it's referring to a file in the tests directory
            if "tests/" in command_lower or any(
                part.startswith("test_") or part.endswith("_test.py")
                for part in command.split()
            ):
                return True

        # Check for distributed testing commands that execute test files
        if "torchrun" in command_lower and (
            "test" in command_lower or "distributed/" in command_lower
        ):
            return True

        return False

    def parse_direct_test_command(self, command: str) -> Tuple[List[str], List[str]]:
        """Parse commands that directly execute test files in the tests/ directory."""
        parts = command.split()
        patterns = []
        ignore_flags = []  # Direct commands don't typically have ignore flags

        # Handle torchrun distributed testing commands
        if "torchrun" in command:
            # Look for Python scripts in torchrun command that are test files
            for i, part in enumerate(parts):
                if part.endswith(".py") and (
                    "test" in part or "distributed/test" in part
                ):
                    # Only process if it's a test file in the tests directory
                    if (
                        "tests/" in part
                        or part.startswith("distributed/test")
                        or part.startswith("test_")
                    ):
                        normalized_path = self._normalize_test_path(part)
                        if normalized_path:
                            patterns.append(normalized_path)
            return patterns, ignore_flags

        # Find the python command and extract the script being executed
        for i, part in enumerate(parts):
            if part in ["python", "python3"]:
                if i + 1 < len(parts):
                    script_path = parts[i + 1]

                    # ONLY handle test files that are in the tests/ directory
                    if "test" in script_path and script_path.endswith(".py"):
                        # Check if it's actually in the tests directory or is a test file
                        if (
                            "tests/" in script_path
                            or script_path.startswith("test_")
                            or script_path.endswith("_test.py")
                        ):
                            normalized_path = self._normalize_test_path(script_path)
                            if normalized_path:
                                patterns.append(normalized_path)
                break

        return patterns, ignore_flags

    def match_pattern(self, pattern: str, ignore_flags: List[str]) -> Set[str]:
        """Properly resolve pytest patterns to actual test files, simulating pytest's discovery logic."""
        matched_files = set()

        # Parse ignore patterns
        ignore_patterns = []
        for ignore_flag in ignore_flags:
            ignore_pattern = (
                ignore_flag.replace("--ignore=", "").replace("--ignore", "").strip()
            )
            if ignore_pattern:
                ignore_patterns.append(ignore_pattern)

        # Clean the pattern
        pattern = pattern.strip()
        if not pattern:
            return matched_files

        # Convert pattern to absolute path for processing
        if os.path.isabs(pattern):
            abs_pattern = pattern
        else:
            abs_pattern = os.path.join(self.tests_dir, pattern)

        # Case 1: Direct file path
        if pattern.endswith(".py"):
            if self._is_test_file(pattern):
                abs_file_path = os.path.join(self.tests_dir, pattern)
                if os.path.exists(abs_file_path):
                    if not self._should_ignore_file(pattern, ignore_patterns):
                        matched_files.add(pattern)

        # Case 2: Directory pattern - find all test files in directory
        elif os.path.isdir(abs_pattern):
            for root, dirs, files in os.walk(abs_pattern):
                # Skip ignored directories early
                dirs[:] = [
                    d
                    for d in dirs
                    if not self._should_ignore_path(
                        os.path.relpath(os.path.join(root, d), self.tests_dir),
                        ignore_patterns,
                    )
                ]

                for file in files:
                    if self._is_test_file(file):
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, self.tests_dir)

                        if not self._should_ignore_file(rel_path, ignore_patterns):
                            matched_files.add(rel_path)

        # Case 3: Glob pattern
        elif "*" in pattern or "?" in pattern or "[" in pattern:
            try:
                # Use glob to find matching paths
                glob_pattern = os.path.join(self.tests_dir, pattern)
                for match_path in glob.glob(glob_pattern, recursive=True):
                    if os.path.isfile(match_path) and self._is_test_file(
                        os.path.basename(match_path)
                    ):
                        rel_path = os.path.relpath(match_path, self.tests_dir)
                        if not self._should_ignore_file(rel_path, ignore_patterns):
                            matched_files.add(rel_path)
                    elif os.path.isdir(match_path):
                        # If glob matches a directory, find test files in it
                        for root, dirs, files in os.walk(match_path):
                            dirs[:] = [
                                d
                                for d in dirs
                                if not self._should_ignore_path(
                                    os.path.relpath(
                                        os.path.join(root, d), self.tests_dir
                                    ),
                                    ignore_patterns,
                                )
                            ]

                            for file in files:
                                if self._is_test_file(file):
                                    file_path = os.path.join(root, file)
                                    rel_path = os.path.relpath(
                                        file_path, self.tests_dir
                                    )
                                    if not self._should_ignore_file(
                                        rel_path, ignore_patterns
                                    ):
                                        matched_files.add(rel_path)
            except Exception:
                # If glob fails, try treating as directory or file
                pass

        # Case 4: Treat as directory if it exists
        else:
            full_path = os.path.join(self.tests_dir, pattern)
            if os.path.exists(full_path):
                if os.path.isdir(full_path):
                    # Directory - find all test files
                    for root, dirs, files in os.walk(full_path):
                        dirs[:] = [
                            d
                            for d in dirs
                            if not self._should_ignore_path(
                                os.path.relpath(os.path.join(root, d), self.tests_dir),
                                ignore_patterns,
                            )
                        ]

                        for file in files:
                            if self._is_test_file(file):
                                file_path = os.path.join(root, file)
                                rel_path = os.path.relpath(file_path, self.tests_dir)
                                if not self._should_ignore_file(
                                    rel_path, ignore_patterns
                                ):
                                    matched_files.add(rel_path)
                elif os.path.isfile(full_path) and self._is_test_file(pattern):
                    # Single file
                    if not self._should_ignore_file(pattern, ignore_patterns):
                        matched_files.add(pattern)

        return matched_files

    def _is_test_file(self, filename: str) -> bool:
        """Check if a file is a test file by pytest conventions."""
        basename = os.path.basename(filename)
        return (
            basename.startswith("test_") or basename.endswith("_test.py")
        ) and basename.endswith(".py")

    def _should_ignore_file(self, file_path: str, ignore_patterns: List[str]) -> bool:
        """Check if a file should be ignored based on ignore patterns."""
        for ignore_pattern in ignore_patterns:
            # Handle different ignore pattern formats
            if self._matches_ignore_pattern(file_path, ignore_pattern):
                return True
        return False

    def _should_ignore_path(self, path: str, ignore_patterns: List[str]) -> bool:
        """Check if a path (file or directory) should be ignored."""
        return self._should_ignore_file(path, ignore_patterns)

    def _matches_ignore_pattern(self, path: str, ignore_pattern: str) -> bool:
        """Check if a path matches an ignore pattern."""
        # Normalize paths
        path = path.replace("\\", "/")
        ignore_pattern = ignore_pattern.replace("\\", "/")

        # Exact match
        if path == ignore_pattern:
            return True

        # Directory prefix match
        if ignore_pattern.endswith("/"):
            return path.startswith(ignore_pattern) or path.startswith(
                ignore_pattern.rstrip("/") + "/"
            )

        # File/directory name match
        if "/" not in ignore_pattern:
            # Match basename
            if os.path.basename(path) == ignore_pattern:
                return True
            # Match any path component
            path_parts = path.split("/")
            if ignore_pattern in path_parts:
                return True

        # Glob pattern match
        if "*" in ignore_pattern or "?" in ignore_pattern or "[" in ignore_pattern:
            if fnmatch.fnmatch(path, ignore_pattern):
                return True
            # Also try basename matching for glob patterns
            if fnmatch.fnmatch(os.path.basename(path), ignore_pattern):
                return True

        # Prefix match (path starts with ignore pattern)
        if path.startswith(ignore_pattern + "/") or path.startswith(ignore_pattern):
            return True

        return False

    def extract_buildkite_scripts_tests(self) -> List[Tuple[str, str]]:
        """Extract pytest commands from buildkite scripts (.sh files)."""
        if not self.buildkite_scripts_dir or not os.path.exists(
            self.buildkite_scripts_dir
        ):
            return []

        pytest_commands = []
        script_files = []

        # Find all .sh files recursively in buildkite scripts directory
        for root, dirs, files in os.walk(self.buildkite_scripts_dir):
            for file in files:
                if file.endswith(".sh"):
                    script_files.append(os.path.join(root, file))

        for script_file in script_files:
            try:
                with open(script_file, "r", encoding="utf-8") as f:
                    content = f.read()

                script_name = os.path.relpath(script_file, self.buildkite_scripts_dir)
                label = f"Buildkite Script: {script_name}"

                # Find pytest commands using regex patterns
                pytest_patterns = [
                    # Direct pytest commands
                    r"\bpytest\s+[^\n]*",
                    # python -m pytest commands
                    r"python3?\s+-m\s+pytest\s+[^\n]*",
                    # Environment variable prefixed pytest commands
                    r"\b[A-Z_]+=\S*\s+pytest\s+[^\n]*",
                    # Environment variable prefixed python -m pytest commands
                    r"\b[A-Z_]+=\S*\s+python3?\s+-m\s+pytest\s+[^\n]*",
                    # Multiple environment variables prefixed pytest
                    r"(?:\b[A-Z_]+=\S*\s+)+pytest\s+[^\n]*",
                    # Multiple environment variables prefixed python -m pytest
                    r"(?:\b[A-Z_]+=\S*\s+)+python3?\s+-m\s+pytest\s+[^\n]*",
                    # Pytest commands inside quoted strings (for function calls)
                    r'"[^"]*pytest[^"]*"',
                    # Pytest commands in single quotes
                    r"'[^']*pytest[^']*'",
                    # Direct execution of test files in tests/ directory ONLY
                    r"python3?\s+tests/[^\s]*test[^\s]*\.py[^\n]*",
                    r"python3?\s+[^\s]*test[^\s]*\.py[^\n]*",
                    # Environment variable prefixed python test executions in tests/ only
                    r"\b[A-Z_]+=\S*\s+python3?\s+tests/[^\s]*test[^\s]*\.py[^\n]*",
                    r"(?:\b[A-Z_]+=\S*\s+)+python3?\s+tests/[^\s]*test[^\s]*\.py[^\n]*",
                    r"\b[A-Z_]+=\S*\s+python3?\s+[^\s]*test[^\s]*\.py[^\n]*",
                    r"(?:\b[A-Z_]+=\S*\s+)+python3?\s+[^\s]*test[^\s]*\.py[^\n]*",
                    # Torchrun distributed testing commands (only if they run test files)
                    r"torchrun\s+[^\n]*distributed/test[^\n]*",
                    r"torchrun\s+[^\n]*test[^\n]*\.py[^\n]*",
                    # Environment variable prefixed torchrun commands (only test files)
                    r"\b[A-Z_]+=\S*\s+torchrun\s+[^\n]*test[^\n]*",
                    r"(?:\b[A-Z_]+=\S*\s+)+torchrun\s+[^\n]*test[^\n]*",
                    # Commands with timeouts
                    r"timeout\s+\d+\s+[^\n]*pytest[^\n]*",
                    # Commands with bash -c wrapping
                    r"bash\s+-c\s+['\"][^'\"]*pytest[^'\"]*['\"]",
                    # Commands inside conditional statements (if/while/until)
                    r"(?:if|while|until)\s+[^;]*pytest[^;]*;",
                    # Background process pytest commands
                    r"[^\n]*pytest[^\n]*&\s*$",
                    # Commands with directory changes and chaining
                    r"cd\s+[^;]*;\s*[^\n]*pytest[^\n]*",
                    # Pip install followed by test execution
                    r"pip\s+install[^\n]*&&[^\n]*pytest[^\n]*",
                    # Multi-line command continuations
                    r"[^\n]*pytest[^\n]*\\\s*\n[^\n]*",
                ]

                for pattern in pytest_patterns:
                    matches = re.findall(pattern, content, re.MULTILINE)
                    for match in matches:
                        # Clean up the command (remove line continuation and extra whitespace)
                        clean_command = re.sub(r"\s*\\\s*\n\s*", " ", match.strip())
                        clean_command = " ".join(clean_command.split())

                        # Remove quotes if the whole command is quoted
                        if (
                            clean_command.startswith('"')
                            and clean_command.endswith('"')
                        ) or (
                            clean_command.startswith("'")
                            and clean_command.endswith("'")
                        ):
                            clean_command = clean_command[1:-1]

                        # Handle command chaining with && or || or ;
                        if any(op in clean_command for op in [" && ", " || ", "; "]):
                            # Split by these operators and process each part
                            parts = re.split(r"\s*(?:&&|\|\||;)\s*", clean_command)
                            for part in parts:
                                part = part.strip()
                                if part and (
                                    "pytest" in part
                                    or self._is_test_execution(part)
                                    or "torchrun" in part
                                ):
                                    pytest_commands.append((label, part))
                        elif clean_command and (
                            "pytest" in clean_command
                            or self._is_test_execution(clean_command)
                            or "torchrun" in clean_command
                        ):
                            pytest_commands.append((label, clean_command))

            except Exception as e:
                print(f"Warning: Could not read script {script_file}: {e}")
                continue

        return pytest_commands

    def analyze(self) -> AnalysisResults:
        with open(self.yaml_file, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        # Extract pytest commands from YAML pipeline
        pytest_commands = self.extract_pytest_commands(yaml_data)

        # Extract pytest commands from buildkite scripts
        buildkite_commands = self.extract_buildkite_scripts_tests()

        # Combine all commands
        all_commands = pytest_commands + buildkite_commands

        all_test_files = self.get_all_test_files()

        file_to_labels = defaultdict(list)
        covered_files = set()

        for label, command in all_commands:
            if "pytest" in command:
                patterns, ignore_flags = self.parse_pytest_command(command)
            else:
                patterns, ignore_flags = self.parse_direct_test_command(command)

            matched_files = set()
            for pattern in patterns:
                if pattern:  # Only process non-empty patterns
                    matched_files.update(self.match_pattern(pattern, ignore_flags))

            # Only count files that actually exist in the all_test_files set
            valid_matched_files = matched_files & all_test_files

            for file_path in valid_matched_files:
                file_to_labels[file_path].append(label)

            covered_files.update(valid_matched_files)

        multiple_coverage = {
            f: labels for f, labels in file_to_labels.items() if len(labels) > 1
        }
        single_coverage = {
            f: labels for f, labels in file_to_labels.items() if len(labels) == 1
        }
        orphan_files = all_test_files - covered_files

        return AnalysisResults(
            all_test_files=all_test_files,
            covered_files=covered_files,
            orphan_files=orphan_files,
            file_to_labels=dict(file_to_labels),
            multiple_coverage=multiple_coverage,
            single_coverage=single_coverage,
            total_pytest_commands=len(all_commands),
        )

    def print_report(self, results: AnalysisResults) -> None:
        # Multiple coverage files
        if results.multiple_coverage:
            print(
                f"TEST FILES RUN MULTIPLE TIMES ({len(results.multiple_coverage)} files):"
            )
            for file_path in sorted(results.multiple_coverage.keys()):
                labels = results.multiple_coverage[file_path]
                print(f"{file_path} ({len(labels)} times): {'; '.join(labels)}")
            print()

        # Single coverage files
        if results.single_coverage:
            print(f"TEST FILES RUN ONCE ({len(results.single_coverage)} files):")
            for file_path in sorted(results.single_coverage.keys()):
                print(f"{file_path} -> {results.single_coverage[file_path][0]}")
            print()

        # Orphan files
        if results.orphan_files:
            print(f"ORPHAN TEST FILES ({len(results.orphan_files)} files):")
            for orphan in sorted(results.orphan_files):
                print(f"{orphan} -> NOT COVERED")
            print()

        # Summary statistics
        total_files = len(results.all_test_files)
        covered_files = len(results.covered_files)
        coverage_pct = (covered_files / total_files * 100) if total_files else 0
        total_test_runs = sum(len(labels) for labels in results.file_to_labels.values())
        avg_coverage = total_test_runs / covered_files if covered_files else 0

        print("SUMMARY:")
        print(f"Total test files: {total_files}")
        print(f"Covered files: {covered_files} ({coverage_pct:.1f}%)")
        print(f"Multiple coverage: {len(results.multiple_coverage)}")
        print(f"Single coverage: {len(results.single_coverage)}")
        print(f"Orphan files: {len(results.orphan_files)}")
        print(f"Avg runs per test: {avg_coverage:.2f}")

    def write_csv(self, results: AnalysisResults, csv_path: str) -> None:
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                ["Test File", "Pipeline Labels", "Coverage Count", "Status"]
            )

            # Covered files
            for file_path in sorted(results.file_to_labels.keys()):
                labels = results.file_to_labels[file_path]
                labels_str = "\n".join(labels)
                count = len(labels)
                status = "MULTIPLE" if count > 1 else "SINGLE"
                writer.writerow([file_path, labels_str, count, status])

            # Orphan files
            for orphan_file in sorted(results.orphan_files):
                writer.writerow([orphan_file, "NOT COVERED", 0, "ORPHAN"])

        print(f"CSV report written to: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze pytest commands in CI pipeline YAML files and buildkite scripts"
    )
    parser.add_argument(
        "--yaml_file",
        help="Path to the test pipeline YAML file",
        default=".buildkite/test-pipeline.yaml",
    )
    parser.add_argument(
        "--tests-dir",
        help="Path to the tests directory",
        default="tests",
    )
    parser.add_argument(
        "--working-dir", help="Working directory to change to before analysis"
    )
    parser.add_argument(
        "--buildkite-scripts-dir",
        help="Path to the buildkite scripts directory",
        default=".buildkite/scripts",
    )
    parser.add_argument(
        "--csv-output",
        help="Path to write CSV report to",
        default="pytest_tests_report.csv",
    )

    args = parser.parse_args()

    try:
        analyzer = PytestPipelineAnalyzer(
            args.yaml_file, args.tests_dir, args.working_dir, args.buildkite_scripts_dir
        )
        results = analyzer.analyze()
        analyzer.print_report(results)

        if args.csv_output:
            analyzer.write_csv(results, args.csv_output)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
