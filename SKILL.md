# IFC Model Inspector

Use this skill when a user asks an assistant to inspect an IFC/BIM model,
summarize basic model contents, list rooms/spaces, or run simple BIM quality
checks.

## Tool Entry Point

Call the Python function:

```python
from ifc_model_inspector import inspect_ifc_model

report = inspect_ifc_model("/path/to/model.ifc")
```

Or call the CLI:

```bash
python ifc_model_inspector.py /path/to/model.ifc --json
```

## Output

The function returns a JSON-compatible dictionary containing:

- `summary`: project/building names and entity counts.
- `storeys`: detected storeys and number of rooms on each.
- `rooms`: detected spaces with names, storeys, and areas where available.
- `doors`: detected doors with ids and names.
- `windows`: detected windows with ids and names.
- `issues`: warnings from rule-based BIM sanity checks.
- `metadata`: parser and threshold information.

## Assistant Guidance

Use the JSON report as external context. Prefer answering from `summary`,
`rooms`, and `issues` instead of reading raw IFC text directly.

Mention limitations when relevant: this prototype does not perform geometric
validation or compute areas from geometry.

