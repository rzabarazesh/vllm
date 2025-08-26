#!/bin/bash

# Simple bootstrap script for coverage pipeline
# This uses the static YAML file instead of the Jinja template approach

set -euo pipefail

echo "Uploading coverage pipeline..."

# Check if we're in the right directory
if [[ ! -f ".buildkite/test-pipeline-coverage.yaml" ]]; then
    echo "Error: test-pipeline-coverage.yaml not found!"
    exit 1
fi

# Upload the pipeline directly
buildkite-agent artifact upload .buildkite/test-pipeline-coverage.yaml
buildkite-agent pipeline upload .buildkite/test-pipeline-coverage.yaml

echo "Coverage pipeline uploaded successfully!"