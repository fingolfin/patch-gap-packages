#!/bin/sh
set -e

cd "$(dirname "$0")"
for d in gap-packages/*/ others/*/ ; do
  (cd "$d" && git diff)
done
