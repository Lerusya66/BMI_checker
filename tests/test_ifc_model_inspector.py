from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ifc_model_inspector import inspect_ifc_model


class IfcModelInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample_path = ROOT / "sample.ifc"
        cls.report = inspect_ifc_model(cls.sample_path)

    def test_summary_counts(self) -> None:
        self.assertEqual(
            self.report["summary"],
            {
                "project_name": None,
                "building_name": None,
                "num_storeys": 3,
                "num_spaces": 4,
                "num_doors": 3,
                "num_windows": 4,
            },
        )

    def test_rooms_are_mapped_to_storeys(self) -> None:
        rooms_by_id = {room["id"]: room for room in self.report["rooms"]}

        self.assertEqual(rooms_by_id["#177"]["storey"], "Ground Floor")
        self.assertEqual(rooms_by_id["#323"]["storey"], "Ground Floor")
        self.assertEqual(rooms_by_id["#421"]["storey"], "Ground Floor")
        self.assertEqual(rooms_by_id["#531"]["storey"], "Roof")

    def test_expected_quality_issues_are_reported(self) -> None:
        messages = {(issue["entity"], issue.get("id"), issue["message"]) for issue in self.report["issues"]}

        self.assertIn(("IfcProject", None, "Missing project name"), messages)
        self.assertIn(("IfcBuilding", None, "Missing building name"), messages)
        self.assertIn(("IfcSpace", "#177", "Room has no name"), messages)
        self.assertIn(("IfcSpace", "#323", "Room has no name"), messages)
        self.assertIn(("IfcSpace", "#421", "Room area is unusually small: 0.05"), messages)
        self.assertIn(("IfcSpace", "#531", "Room area is missing"), messages)
        self.assertIn(("IfcBuildingStorey", "#83873", "Storey has no rooms"), messages)
        self.assertIn(("IfcDoor", "#10993", "Door has no name"), messages)
        self.assertIn(("IfcWindow", "#33350", "Window has no name"), messages)
        self.assertEqual(len(self.report["issues"]), 9)

    def test_cli_json_output(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "ifc_model_inspector.py"), str(self.sample_path), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["summary"]["num_spaces"], 4)
        self.assertEqual(len(payload["issues"]), 9)


if __name__ == "__main__":
    unittest.main()
