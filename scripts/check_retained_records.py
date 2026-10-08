"""Recompute supplied observations; does not execute a new service study."""
from pathlib import Path
import json
import runpy

checks = runpy.run_path(str(Path(__file__).with_name("verify.py")))
names = ["check_principal", "check_speaches", "check_uipath", "check_replay",
         "check_executable_perturbations", "check_native_mutation_matrix",
         "check_topology_challenge", "check_gate_ablation", "check_release_lineage",
         "check_mutations", "check_counterfactuals", "check_costs"]
print(json.dumps({name: checks[name]() for name in names}, indent=2))
