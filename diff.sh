#!/bin/sh
set -e

for d in */ ; do
  (cd "$d" && git diff)
done
