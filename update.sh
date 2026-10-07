#!/bin/sh
set -e

cd "$(dirname "$0")"
find gap-packages others -mindepth 1 -maxdepth 1 -type d | \
parallel --bar --jobs 0 '
  cd {} &&
  if ! git pull --ff-only > /dev/null 2>&1; then
    echo "❌ There was an error pulling in directory: {}"
  fi
'

exit 0
