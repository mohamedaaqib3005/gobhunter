#!/bin/bash
source .venv/bin/activate
python main.py scrape >> scrape.log 2>&1
