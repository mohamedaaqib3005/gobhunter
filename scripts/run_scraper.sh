#!/bin/bash
cd "/home/george/Bit by Bit/job-automation"
source .venv/bin/activate
python main.py scrape >> /home/george/Bit\ by\ Bit/job-automation/logs/scrape.log 2>&1
