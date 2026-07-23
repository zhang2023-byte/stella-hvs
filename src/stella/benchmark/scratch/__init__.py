"""Isolated hvs_extraction_scratch development pipeline.

Implements the frozen scratch design in
``benchmark/hvs_extraction_scratch_decisions.yaml`` (D001-D054). The scratch
pipeline never reads gold, scorecards, private reports, test results, or
previous run outputs, and never writes into formal campaign run directories
(``benchmark/campaigns/**``). Paper inputs come only from
``literature/<arxiv_id>/``; run outputs stay under the locally ignored
``benchmark/scratch/`` tree.
"""
