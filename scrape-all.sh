#!/usr/bin/env bash
set -u

QUERIES=(
  "Frontend Developer"
  "Full Stack Developer"
  "React Developer"
  "UI Developer"
  "JavaScript Developer"
  "Mobile App Developer"
  "Web Developer"
  "WordPress Developer"
)

for q in "${QUERIES[@]}"; do
  echo "=== $q ==="
  SEARCH_QUERY="$q" python main.py scrape
done

python main.py deduplicate
python main.py cleanup
