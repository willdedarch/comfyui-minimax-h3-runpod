#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
    echo 'Usage: bash scripts/build_image.sh registry/account/h3-max:2026-09-23' >&2
    exit 2
fi
h3max_image="$1"
h3max_package="$(cd "$(dirname "$0")/.." && pwd)"
docker build --platform linux/amd64 --tag "$h3max_image" "$h3max_package"
echo "Build finished: $h3max_image"
echo 'Review the build output, then publish with docker push using the same image name.'
