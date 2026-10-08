#!/bin/sh
# Execute from any working directory. Does not install packages or contact services.
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
export PYTHONPATH="$PWD/src:$PWD/vendor"

python scripts/verify_release_lineage.py
python scripts/audit_references.py
python scripts/verify.py
python -m pytest -q
python scripts/run_native.py --output results/reproduced-native.json

# Fresh independent replay of the 40-configuration principal matrix.
python scripts/run_matrix.py --output results/reproduced --repeats 20 --workers 2
python scripts/compare_replay.py \
  --replay results/reproduced \
  --output results/reproduced-comparison.json

# Independent public-source boundaries.
python scripts/run_speaches_holdout.py \
  --output results/reproduced-speaches --repeats 10
python scripts/run_uipath_holdout.py \
  --output results/reproduced-uipath --repeats 10 --workers 2 --variant public
python scripts/run_uipath_holdout.py \
  --output results/reproduced-uipath-correction --repeats 10 --workers 2 \
  --variant local-correction

# Executable, topology, native-test, and derived decision challenges.
python scripts/run_topology_challenge.py \
  --output results/reproduced-topology --repeats 1 --workers 2
python scripts/run_executable_perturbations.py \
  --output results/reproduced-executable-perturbations --repeats 10 --workers 2
python scripts/run_native_mutation_matrix.py \
  --output results/reproduced-native-matrix --workers 2
python scripts/run_mutation_challenge.py --output results/reproduced-mutations
python scripts/analyze_policy_counterfactual.py --output results/reproduced-policy
python scripts/analyze_gate_ablation.py --output results/reproduced-gates

# No concurrent fidelity jobs during the cost experiment.
python scripts/benchmark.py --output results/reproduced-costs
python scripts/summarize.py \
  --trial-dir results/reproduced \
  --cost-dir results/reproduced-costs \
  --output results/reproduced-summary --no-paper

# Regenerate the published paper's tables from retained observations.
python scripts/summarize.py
python scripts/check_metric_consistency.py
python scripts/build_paper_assets.py
python scripts/verify.py
cd ../paper
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
