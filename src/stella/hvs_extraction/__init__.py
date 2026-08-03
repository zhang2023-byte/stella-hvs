"""Canonical staged HVS candidate extraction engine.

The engine reads only paper-local archived inputs, freezes an immutable V6 run
before any provider request, and emits v3 core artifacts plus operational run
records. It never reads private gold, scorecards, reports, test results, or
previous run outputs.
"""
