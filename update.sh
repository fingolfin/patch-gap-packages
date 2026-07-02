#!/bin/sh
set -e

find . -mindepth 1 -maxdepth 1 -type d | \
parallel --bar --jobs 0 '
  cd {} &&
  if ! git pull --ff-only > /dev/null 2>&1; then
    echo "❌ There was an error pulling in directory: {}"
  fi
'

exit 0
