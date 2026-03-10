# Career Agent

A Python CLI tool that scans job sources, stores postings locally,
scores them against a skill profile, and ranks the best opportunities.

## Features

- Multi-source job ingestion (RSS + JSON)
- Local SQLite database
- Heuristic job scoring
- Ranked job recommendations
- Remote-only filtering
- Explainable scoring

## Example

career-agent scan
career-agent score-all
career-agent top --remote-only --min-score 60

## Tech Stack

- Python
- Typer CLI
- SQLite
- RSS parsing