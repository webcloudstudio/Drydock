# Increment Review — Price Importer

The agent finished the price importer and is requesting sign-off. This page is a normal
markdown document with `"review": true` set on its item, so a decision bar appears at the
bottom: **Approve · Revise · Reject** with optional feedback. The decision is recorded and
shown as a coloured banner.

## What was built
- Daily OHLCV download and normalization
- Health endpoint and a smoke test

## How to try it
```bash
./bin/start.sh && curl localhost:8000/health
```

## What is open
- Retry policy on `429` is still under review (see the Kanban story STORY-3).

Sign off below, or send it back with a note.
