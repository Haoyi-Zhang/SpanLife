#!/usr/bin/env python3
"""Repeat only the two held-out BackgroundTasks paths after harness correction."""
import run_matrix
run_matrix.MATRIX = [("service_background_gap", "fixed"), ("service_background_corrected", "fixed")]
if __name__ == '__main__':
    raise SystemExit(run_matrix.main())
