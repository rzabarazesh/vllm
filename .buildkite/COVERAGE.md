# Test Coverage Collection for vLLM

This document describes the minimal test coverage collection system added to the vLLM Buildkite pipeline.

## Overview

The coverage system has been designed with minimal code changes to collect test coverage data across all test jobs and generate comprehensive coverage reports.

## Components

### 1. Dependencies
- `pytest-cov>=4.0.0` - Pytest plugin for coverage collection
- `coverage[toml]>=7.0.0` - Core coverage measurement library

### 2. Scripts
- `.buildkite/scripts/pytest-with-coverage.sh` - Wrapper script for pytest with coverage
- `.buildkite/scripts/generate-coverage-report.sh` - Coverage report generation script

### 3. Configuration
- Coverage configuration is defined in `pyproject.toml` under `[tool.coverage.*]` sections
- Excludes test files, third-party code, and build artifacts from coverage measurement

## Usage

### Enabling Coverage Collection

Coverage collection is controlled by the `VLLM_ENABLE_COVERAGE` environment variable:

```bash
# Enable coverage collection
export VLLM_ENABLE_COVERAGE=1

# Disable coverage collection (default)
export VLLM_ENABLE_COVERAGE=0
```

### In Buildkite Pipeline

To enable coverage collection for a pipeline run:

1. Set the environment variable in your pipeline trigger:
   ```yaml
   env:
     VLLM_ENABLE_COVERAGE: "1"
   ```

2. The coverage report generation step will automatically run after all tests complete

### Local Development

To run tests with coverage locally:

```bash
# Enable coverage
export VLLM_ENABLE_COVERAGE=1

# Run tests (coverage will be collected automatically)
pytest tests/

# Generate coverage report
.buildkite/scripts/generate-coverage-report.sh
```

## Coverage Reports

When coverage is enabled, the following reports are generated:

1. **Terminal Report** - Summary displayed in the build logs
2. **XML Report** - `coverage.xml` for CI tools and integrations
3. **HTML Report** - `coverage_html_report/` directory with detailed interactive report

### Buildkite Artifacts

The following artifacts are uploaded when coverage is enabled:
- `coverage.xml` - Machine-readable coverage data
- `coverage_html_report/**/*` - Interactive HTML coverage report

### Buildkite Annotations

A coverage summary annotation is automatically added to the build with the overall coverage percentage.

## Configuration Details

### Coverage Measurement
- **Source**: Only `vllm/` package code is measured
- **Branch Coverage**: Enabled for more detailed analysis
- **Parallel**: Supports parallel test execution with data combination

### Exclusions
- Test files (`*/tests/*`, `*/test_*`)
- Third-party code (`vllm/third_party/*`)
- Version files (`vllm/_version.py`)
- Build artifacts (`*/build/*`, `*/dist/*`)

### Report Exclusions
- Pragma comments (`# pragma: no cover`)
- Debug code (`if self.debug:`)
- Abstract methods
- Protocol classes
- Exception raising code

## Implementation Details

### Minimal Changes Approach

The implementation follows a minimal changes approach:

1. **No Test Modifications**: Existing tests run unchanged
2. **Optional Coverage**: Coverage collection is opt-in via environment variable
3. **Wrapper Scripts**: Use wrapper scripts instead of modifying existing commands
4. **Separate Report Step**: Coverage reporting runs as a separate pipeline step

### Data Collection Strategy

1. Each test job creates a unique coverage data file using `BUILDKITE_JOB_ID`
2. Coverage data files are stored in `coverage_data/` directory
3. The report generation step combines all coverage files
4. Reports are generated and uploaded as artifacts

## Troubleshooting

### Coverage Not Collected
- Ensure `VLLM_ENABLE_COVERAGE=1` is set
- Check that coverage dependencies are installed
- Verify the `coverage_data/` directory is created

### Missing Coverage Data
- Check that test jobs completed successfully
- Verify coverage data files exist in `coverage_data/.coverage.*`
- Ensure the report generation step has access to all coverage files

### Low Coverage Numbers
- Review the exclusion patterns in `pyproject.toml`
- Check if test files are properly excluded
- Verify that the source patterns match your code structure

## Future Enhancements

Potential improvements that could be added:

1. **Coverage Thresholds**: Fail builds if coverage drops below a threshold
2. **Diff Coverage**: Only measure coverage for changed files
3. **Coverage Trends**: Track coverage changes over time
4. **Integration**: Connect with external coverage tracking services
5. **Parallel Optimization**: Optimize coverage data collection for large test suites

## Dependencies Update

After adding coverage dependencies to `requirements/test.in`, regenerate the requirements file:

```bash
uv pip compile requirements/test.in -o requirements/test.txt --index-strategy unsafe-best-match --torch-backend cu128
```