# VLLM Coverage Pipeline

This is a modified version of the VLLM CI pipeline that generates test coverage reports.

## Files Created

1. **test-pipeline-coverage.yaml** - The modified pipeline with 3 test steps that include coverage reporting
2. **bootstrap-coverage.sh** - Simple bootstrap script to upload the pipeline
3. **README-coverage.md** - This documentation

## How It Works

### Pipeline Structure
The coverage pipeline includes 3 main test steps from the original pipeline:

1. **Core Test (Coverage)** - Tests core VLLM functionality with coverage
2. **Async Engine, Inputs, Utils, Worker Test (Coverage)** - Tests async components with coverage  
3. **Basic Correctness Test (Coverage)** - Tests basic correctness with coverage
4. **Combine Coverage Reports** - Final step that combines all coverage data

### Coverage Collection
Each test step uses a unique `COVERAGE_FILE` environment variable:
- Uses `pytest-cov` to collect coverage data
- Each test creates a separate `.coverage.*` file
- Final step combines all coverage files using `coverage combine`

### Coverage Output
The final step generates:
- Console coverage report with `coverage report --show-missing`
- HTML coverage report in `coverage_html_report/`
- XML coverage report as `coverage.xml`

## Usage

### Option 1: Use Buildkite Pipeline
1. Create a new Buildkite pipeline that points to your vLLM repository
2. Set the pipeline steps to use `bash .buildkite/bootstrap-coverage.sh`
3. Trigger the pipeline

### Option 2: Manual Upload
If you're in the VLLM repository directory:
```bash
cd /path/to/vllm
./.buildkite/bootstrap-coverage.sh
```

### Option 3: Use with CI-Infra Template (Advanced)
If you want to integrate with the existing ci-infra Jinja template system:
1. Modify the Jinja template to accept a coverage mode parameter
2. Update the bootstrap script to use the template rendering
3. This would require more complex changes to the ci-infra repository

## Key Features

- **Simplified Pipeline**: Only runs 3 essential test suites to keep runtime manageable
- **Unique Coverage Files**: Each test creates separate coverage data to avoid conflicts
- **Combined Reports**: Final step merges all coverage data for comprehensive reporting
- **Minimal Dependencies**: Uses standard pytest-cov and coverage tools
- **Artifact Generation**: Creates both HTML and XML reports for different use cases

## Notes

- This is designed for one-off coverage reports, not production CI
- Uses `--cov-report=` to suppress individual reports and only generate the final combined report
- The pipeline maintains the same source file dependencies as the original tests
- Uses the same hardware queues (`amdexperimental`) as the original pipeline