#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "cockpit-agent"))
suite = unittest.defaultTestLoader.loadTestsFromNames([
    "interview.engine_tests", "interview.integration_tests",
    "interview.expanded_tests", "interview.api_tests",
])
suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_expanded_services.py"))
suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_chat_routing.py"))
suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_navigation_questions.py"))
suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_release_config.py"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
