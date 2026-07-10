# IFC Model Inspector Skill

A small Python skill for inspecting IFC/BIM models and producing a structured
JSON report that an LLM assistant can use as external context.

The tool extracts basic IFC entities, lists rooms/spaces, maps rooms to storeys
when possible, and runs simple BIM sanity checks.

## Quick Start

```bash
python ifc_model_inspector.py sample.ifc --json --pretty
```

Human-readable output is available by omitting `--json`:

```bash
python ifc_model_inspector.py sample.ifc
```

Use a different small-area threshold:

```bash
python ifc_model_inspector.py sample.ifc --json --small-area-threshold 2.0
```

## Installation

The inspector works without third-party packages by using its built-in fallback
STEP parser. For better IFC coverage, install `ifcopenshell`:

```bash
python -m pip install -r requirements.txt
```

`ifcopenshell` is recommended for real IFC files. The fallback parser is scoped
to the entities and relations needed by this assignment.

## Python API

```python
from ifc_model_inspector import inspect_ifc_model

report = inspect_ifc_model("sample.ifc")
print(report["summary"])
```

The returned object is JSON-compatible and has this shape:

```json
{
  "summary": {
    "project_name": null,
    "building_name": null,
    "num_storeys": 3,
    "num_spaces": 4,
    "num_doors": 3,
    "num_windows": 4
  },
  "rooms": [],
  "issues": []
}
```

See [examples/example_output.json](examples/example_output.json) for a full
sample report.

## What It Extracts

- `IfcProject`: project name when present.
- `IfcBuilding`: building name when present.
- `IfcBuildingStorey`: storey name, elevation, and number of spaces.
- `IfcSpace`: room/space name, long name, storey, and room area when available.
- `IfcDoor`: id and name.
- `IfcWindow`: id and name.

Room-to-storey mapping is detected from `IfcRelAggregates`. Areas are extracted
from `IfcElementQuantity` values named `NetFloorArea` or `GrossFloorArea`; the
code also supports a fallback to a property named `Area` when it is actually
attached to the space.

## Sanity Checks

The tool currently reports warnings for:

- Missing project name.
- Missing building name.
- Rooms/spaces without names.
- Storeys without rooms.
- Missing room area.
- Unusually small room area.
- Doors without names.
- Windows without names.

The default small-area threshold is `1.0` square meter.

## Sample IFC Findings

For the provided `sample.ifc`, the report finds:

- 3 storeys.
- 4 spaces.
- 3 doors.
- 4 windows.
- 9 warnings:
  - missing project name;
  - missing building name;
  - 2 unnamed rooms;
  - 1 unusually small room;
  - 1 room with missing area;
  - 1 empty storey;
  - 1 unnamed door;
  - 1 unnamed window.

## Tests

Run the tests with the standard library:

```bash
python -m unittest discover -s tests
```

If `pytest` is installed, this also works:

```bash
pytest
```

## LLM Assistant Integration

An LLM assistant should not parse IFC text directly in a prompt. Instead, it can
call this skill as an external tool:

1. Pass the IFC file path to `inspect_ifc_model()`.
2. Receive a compact JSON report.
3. Use `summary`, `rooms`, `storeys`, and `issues` to answer user questions.
4. Cite limitations from `metadata` or from the README when the user asks for
   detailed BIM validation.

Example tool wrapper:

```python
def answer_with_ifc_context(ifc_path: str, user_question: str) -> dict:
    model_context = inspect_ifc_model(ifc_path)
    return {
        "question": user_question,
        "ifc_context": model_context,
    }
```

## Limitations

This is a small rule-based prototype, not a full BIM validation engine.

- It does not validate geometry.
- It does not compute room areas from meshes or profiles.
- It handles only a focused set of IFC entities.
- Storey and property extraction depends on common IFC relationships.
- The fallback parser is intentionally narrow; install `ifcopenshell` for more
  robust handling of real-world IFC files.

