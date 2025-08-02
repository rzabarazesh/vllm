#!/bin/bash
set -e

# Coverage report generation script for vLLM Buildkite pipeline
# This script combines coverage data from all test jobs and generates reports

echo "📊 Generating coverage reports..."

# Create coverage directory if it doesn't exist
mkdir -p coverage_data

# Combine all coverage files
echo "Combining coverage data files..."
coverage combine coverage_data/.coverage.*

# Generate coverage reports
echo "Generating coverage reports..."

# Generate terminal report
echo "=== Coverage Summary ==="
coverage report --show-missing

# Generate XML report for CI tools
coverage xml -o coverage.xml

# Generate HTML report for detailed viewing
coverage html

# Upload coverage data as Buildkite artifact
if [ -n "$BUILDKITE" ]; then
    echo "Uploading coverage reports as artifacts..."
    buildkite-agent artifact upload "coverage.xml"
    buildkite-agent artifact upload "coverage_html_report/**/*"

    # Extract coverage percentage for annotation
    COVERAGE_PERCENT=$(coverage report --format=total)
    echo "📊 Overall test coverage: ${COVERAGE_PERCENT}%" | buildkite-agent annotate --style "info" --context "coverage"
fi

echo "✅ Coverage reports generated successfully!"
echo "📁 HTML report available in: coverage_html_report/"
echo "📄 XML report available at: coverage.xml"
