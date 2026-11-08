"""Run every agent version one by one with its matching test suite.

Usage (from the L1 folder):
    python run_tests.py                 # run all versions in order
    python run_tests.py v1.0.1          # run only the given version(s)
"""
import sys

import agent_v1_0_0
import agent_v1_0_1
import agent_v2_0_0
import test_cases_system_prompt
import test_cases_tools
from common import run_test_cases

# (version, agent module, test suite name, test cases), in run order
RUNS = [
    ("v1.0.0", agent_v1_0_0, "system_prompt", test_cases_system_prompt.TEST_CASES),
    ("v1.0.1", agent_v1_0_1, "system_prompt", test_cases_system_prompt.TEST_CASES),
    ("v2.0.0", agent_v2_0_0, "tools", test_cases_tools.TEST_CASES),
]

if __name__ == "__main__":
    selected = sys.argv[1:]
    known = [version for version, *_ in RUNS]
    unknown = [v for v in selected if v not in known]
    if unknown:
        sys.exit(f"Unknown version(s): {', '.join(unknown)}. Choose from: {', '.join(known)}")

    for version, agent, suite, cases in RUNS:
        if selected and version not in selected:
            continue
        print("\n" + "#" * 70)
        print(f"# AGENT {version} | suite: {suite} | {len(cases)} cases")
        print("#" * 70 + "\n")
        run_test_cases(agent.messages[0], cases, agent.get_approval_routing)
