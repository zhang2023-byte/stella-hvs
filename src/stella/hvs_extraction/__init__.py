"""Isolated hvs_candidate_extraction development pipeline.

Implements the frozen extraction design in
``benchmark/hvs_candidate_extraction_decisions.yaml`` (D001-D054). The extraction
pipeline never reads gold, scorecards, private reports, test results, or
previous run outputs, and never writes into formal campaign run directories
(``benchmark/campaigns/**``). Paper inputs come only from
``literature/<arxiv_id>/``; run outputs stay under the locally ignored
``benchmark/extraction/`` tree.
"""
