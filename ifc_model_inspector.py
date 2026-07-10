"""Small IFC/BIM model inspector skill.

The public entry point is inspect_ifc_model(). The module also exposes a
minimal CLI:

    python ifc_model_inspector.py sample.ifc --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SMALL_AREA_THRESHOLD = 1.0


@dataclass
class Entity:
    """A tiny representation used by the built-in STEP fallback parser."""

    id: str
    type: str
    args: list[str]


@dataclass
class SpaceRecord:
    id: str
    name: str | None
    long_name: str | None = None
    storey: str | None = None
    area: float | None = None
    source: str | None = None


@dataclass
class StoreyRecord:
    id: str
    name: str | None
    elevation: float | None = None
    spaces: list[str] = field(default_factory=list)


def inspect_ifc_model(
    path: str | Path,
    small_area_threshold: float = SMALL_AREA_THRESHOLD,
) -> dict[str, Any]:
    """Inspect an IFC file and return an LLM-friendly JSON-compatible report.

    The function tries to use ifcopenshell when it is installed. If it is not
    available, it falls back to a small STEP parser that extracts the entities
    required by this assignment.
    """

    model_path = Path(path)
    if not model_path.exists():
        raise FileNotFoundError(f"IFC file not found: {model_path}")

    try:
        import ifcopenshell  # type: ignore
    except ImportError:
        return _inspect_with_fallback_parser(model_path, small_area_threshold)

    model = ifcopenshell.open(str(model_path))
    return _inspect_with_ifcopenshell(model, small_area_threshold)


def _inspect_with_ifcopenshell(model: Any, small_area_threshold: float) -> dict[str, Any]:
    projects = list(model.by_type("IfcProject"))
    buildings = list(model.by_type("IfcBuilding"))
    storey_entities = list(model.by_type("IfcBuildingStorey"))
    space_entities = list(model.by_type("IfcSpace"))
    door_entities = list(model.by_type("IfcDoor"))
    window_entities = list(model.by_type("IfcWindow"))

    project_name = _clean(getattr(projects[0], "Name", None)) if projects else None
    building_name = _clean(getattr(buildings[0], "Name", None)) if buildings else None

    storeys: dict[str, StoreyRecord] = {}
    for storey in storey_entities:
        storeys[_entity_id(storey)] = StoreyRecord(
            id=_entity_id(storey),
            name=_clean(getattr(storey, "Name", None)),
            elevation=_to_float(getattr(storey, "Elevation", None)),
        )

    spaces: dict[str, SpaceRecord] = {}
    for space in space_entities:
        space_id = _entity_id(space)
        record = SpaceRecord(
            id=space_id,
            name=_clean(getattr(space, "Name", None)),
            long_name=_clean(getattr(space, "LongName", None)),
            area=_area_from_ifcopenshell_space(space),
        )
        storey = _storey_for_ifcopenshell_space(space)
        if storey is not None:
            storey_id = _entity_id(storey)
            record.storey = _clean(getattr(storey, "Name", None))
            if storey_id in storeys:
                storeys[storey_id].spaces.append(space_id)
        spaces[space_id] = record

    doors = [_named_entity(entity) for entity in door_entities]
    windows = [_named_entity(entity) for entity in window_entities]

    return _build_report(
        project_name=project_name,
        building_name=building_name,
        storeys=storeys,
        spaces=spaces,
        doors=doors,
        windows=windows,
        small_area_threshold=small_area_threshold,
        parser="ifcopenshell",
    )


def _inspect_with_fallback_parser(path: Path, small_area_threshold: float) -> dict[str, Any]:
    entities = _parse_step_entities(path.read_text(encoding="utf-8", errors="replace"))

    projects = _entities_by_type(entities, "IFCPROJECT")
    buildings = _entities_by_type(entities, "IFCBUILDING")
    project_name = _ifc_value(projects[0].args[2]) if projects else None
    building_name = _ifc_value(buildings[0].args[2]) if buildings else None

    storeys: dict[str, StoreyRecord] = {}
    for entity in _entities_by_type(entities, "IFCBUILDINGSTOREY"):
        storeys[entity.id] = StoreyRecord(
            id=entity.id,
            name=_ifc_value(_arg(entity, 2)),
            elevation=_to_float(_ifc_value(_arg(entity, 9))),
        )

    spaces: dict[str, SpaceRecord] = {}
    for entity in _entities_by_type(entities, "IFCSPACE"):
        spaces[entity.id] = SpaceRecord(
            id=entity.id,
            name=_ifc_value(_arg(entity, 2)),
            long_name=_ifc_value(_arg(entity, 7)),
        )

    _attach_spaces_to_storeys(entities, storeys, spaces)
    _attach_space_areas(entities, spaces)

    doors = [_named_entity_from_step(entity) for entity in _entities_by_type(entities, "IFCDOOR")]
    windows = [_named_entity_from_step(entity) for entity in _entities_by_type(entities, "IFCWINDOW")]

    return _build_report(
        project_name=project_name,
        building_name=building_name,
        storeys=storeys,
        spaces=spaces,
        doors=doors,
        windows=windows,
        small_area_threshold=small_area_threshold,
        parser="fallback-step-parser",
    )


def _build_report(
    *,
    project_name: str | None,
    building_name: str | None,
    storeys: dict[str, StoreyRecord],
    spaces: dict[str, SpaceRecord],
    doors: list[dict[str, str | None]],
    windows: list[dict[str, str | None]],
    small_area_threshold: float,
    parser: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    if not project_name:
        issues.append(_issue("warning", "IfcProject", None, "Missing project name"))
    if not building_name:
        issues.append(_issue("warning", "IfcBuilding", None, "Missing building name"))

    for space in spaces.values():
        label = space.name or space.long_name
        if not space.name:
            issues.append(_issue("warning", "IfcSpace", space.id, "Room has no name", label=label))
        if space.area is None:
            issues.append(_issue("warning", "IfcSpace", space.id, "Room area is missing", label=label))
        elif space.area < small_area_threshold:
            issues.append(
                _issue(
                    "warning",
                    "IfcSpace",
                    space.id,
                    f"Room area is unusually small: {space.area:g}",
                    label=label,
                )
            )

    for storey in storeys.values():
        if not storey.spaces:
            issues.append(
                _issue(
                    "warning",
                    "IfcBuildingStorey",
                    storey.id,
                    "Storey has no rooms",
                    label=storey.name,
                )
            )

    for door in doors:
        if not door["name"]:
            issues.append(_issue("warning", "IfcDoor", door["id"], "Door has no name"))

    for window in windows:
        if not window["name"]:
            issues.append(_issue("warning", "IfcWindow", window["id"], "Window has no name"))

    rooms = [
        {
            "id": space.id,
            "name": space.name,
            "long_name": space.long_name,
            "storey": space.storey,
            "area": space.area,
        }
        for space in spaces.values()
    ]

    return {
        "summary": {
            "project_name": project_name,
            "building_name": building_name,
            "num_storeys": len(storeys),
            "num_spaces": len(spaces),
            "num_doors": len(doors),
            "num_windows": len(windows),
        },
        "storeys": [
            {
                "id": storey.id,
                "name": storey.name,
                "elevation": storey.elevation,
                "num_spaces": len(storey.spaces),
            }
            for storey in storeys.values()
        ],
        "rooms": rooms,
        "doors": doors,
        "windows": windows,
        "issues": issues,
        "metadata": {
            "parser": parser,
            "small_area_threshold": small_area_threshold,
        },
    }


def _area_from_ifcopenshell_space(space: Any) -> float | None:
    for definition in getattr(space, "IsDefinedBy", []) or []:
        related = getattr(definition, "RelatingPropertyDefinition", None)
        if related is None:
            continue

        if related.is_a("IfcElementQuantity"):
            for quantity in getattr(related, "Quantities", []) or []:
                if not quantity.is_a("IfcQuantityArea"):
                    continue
                if getattr(quantity, "Name", None) in {"NetFloorArea", "GrossFloorArea"}:
                    return _to_float(getattr(quantity, "AreaValue", None))

        if related.is_a("IfcPropertySet"):
            for prop in getattr(related, "HasProperties", []) or []:
                if getattr(prop, "Name", None) == "Area":
                    value = getattr(getattr(prop, "NominalValue", None), "wrappedValue", None)
                    return _to_float(value)

    return None


def _storey_for_ifcopenshell_space(space: Any) -> Any | None:
    for rel in getattr(space, "Decomposes", []) or []:
        parent = getattr(rel, "RelatingObject", None)
        if parent is not None and parent.is_a("IfcBuildingStorey"):
            return parent

    for rel in getattr(space, "ContainedInStructure", []) or []:
        parent = getattr(rel, "RelatingStructure", None)
        if parent is not None and parent.is_a("IfcBuildingStorey"):
            return parent

    return None


def _parse_step_entities(text: str) -> dict[str, Entity]:
    entities: dict[str, Entity] = {}
    pattern = re.compile(r"#(\d+)=([A-Z0-9_]+)\((.*?)\);", re.DOTALL)
    for match in pattern.finditer(text):
        entity_id = f"#{match.group(1)}"
        entity_type = match.group(2)
        entities[entity_id] = Entity(entity_id, entity_type, _split_step_args(match.group(3)))
    return entities


def _split_step_args(body: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    index = 0

    while index < len(body):
        char = body[index]
        current.append(char)

        if in_string:
            if char == "'":
                if index + 1 < len(body) and body[index + 1] == "'":
                    current.append(body[index + 1])
                    index += 1
                else:
                    in_string = False
        else:
            if char == "'":
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                current.pop()
                args.append("".join(current).strip())
                current = []

        index += 1

    args.append("".join(current).strip())
    return args


def _attach_spaces_to_storeys(
    entities: dict[str, Entity],
    storeys: dict[str, StoreyRecord],
    spaces: dict[str, SpaceRecord],
) -> None:
    for rel in _entities_by_type(entities, "IFCRELAGGREGATES"):
        parent_id = _arg(rel, 4)
        if parent_id not in storeys:
            continue

        for child_id in _refs(_arg(rel, 5)):
            if child_id in spaces:
                spaces[child_id].storey = storeys[parent_id].name
                storeys[parent_id].spaces.append(child_id)


def _attach_space_areas(entities: dict[str, Entity], spaces: dict[str, SpaceRecord]) -> None:
    quantity_values: dict[str, tuple[str | None, float | None]] = {}
    property_values: dict[str, tuple[str | None, float | None]] = {}

    for entity in entities.values():
        if entity.type == "IFCQUANTITYAREA":
            quantity_values[entity.id] = (_ifc_value(_arg(entity, 0)), _to_float(_ifc_value(_arg(entity, 3))))
        elif entity.type == "IFCPROPERTYSINGLEVALUE":
            property_values[entity.id] = (_ifc_value(_arg(entity, 0)), _to_float(_ifc_value(_arg(entity, 2))))

    for rel in _entities_by_type(entities, "IFCRELDEFINESBYPROPERTIES"):
        related_ids = _refs(_arg(rel, 4))
        definition_id = _arg(rel, 5)
        definition = entities.get(definition_id)
        if definition is None:
            continue

        if definition.type == "IFCELEMENTQUANTITY":
            for quantity_id in _refs(_arg(definition, 5)):
                quantity_name, area = quantity_values.get(quantity_id, (None, None))
                if quantity_name not in {"NetFloorArea", "GrossFloorArea"} or area is None:
                    continue
                for related_id in related_ids:
                    if related_id in spaces and spaces[related_id].area is None:
                        spaces[related_id].area = area
                        spaces[related_id].source = quantity_name

        elif definition.type == "IFCPROPERTYSET":
            for property_id in _refs(_arg(definition, 4)):
                property_name, area = property_values.get(property_id, (None, None))
                if property_name != "Area" or area is None:
                    continue
                for related_id in related_ids:
                    if related_id in spaces and spaces[related_id].area is None:
                        spaces[related_id].area = area
                        spaces[related_id].source = "PropertySet.Area"


def _entities_by_type(entities: dict[str, Entity], entity_type: str) -> list[Entity]:
    return [entity for entity in entities.values() if entity.type == entity_type]


def _named_entity(entity: Any) -> dict[str, str | None]:
    return {"id": _entity_id(entity), "name": _clean(getattr(entity, "Name", None))}


def _named_entity_from_step(entity: Entity) -> dict[str, str | None]:
    return {"id": entity.id, "name": _ifc_value(_arg(entity, 2))}


def _entity_id(entity: Any) -> str:
    return f"#{entity.id()}" if callable(getattr(entity, "id", None)) else str(entity)


def _issue(
    severity: str,
    entity: str,
    entity_id: str | None,
    message: str,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {"severity": severity, "entity": entity, "message": message}
    if entity_id:
        issue["id"] = entity_id
    if label:
        issue["label"] = label
    return issue


def _ifc_value(raw: str | None) -> str | None:
    if raw is None:
        return None

    value = raw.strip()
    if value in {"", "$", "*"}:
        return None

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")

    typed_value = re.fullmatch(r"IFC[A-Z0-9_]+\((.*)\)", value, flags=re.DOTALL)
    if typed_value:
        return _ifc_value(typed_value.group(1))

    return value


def _refs(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return re.findall(r"#\d+", raw)


def _arg(entity: Entity, index: int) -> str | None:
    if index >= len(entity.args):
        return None
    return entity.args[index]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _human_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "IFC model inspection report",
        "",
        f"Project: {summary['project_name'] or '<missing>'}",
        f"Building: {summary['building_name'] or '<missing>'}",
        (
            "Counts: "
            f"{summary['num_storeys']} storeys, "
            f"{summary['num_spaces']} spaces, "
            f"{summary['num_doors']} doors, "
            f"{summary['num_windows']} windows"
        ),
        "",
        "Rooms:",
    ]

    for room in report["rooms"]:
        area = room["area"] if room["area"] is not None else "missing"
        lines.append(
            f"- {room['id']}: {room['name'] or '<missing>'} "
            f"on {room['storey'] or '<unknown storey>'}, area={area}"
        )

    lines.extend(["", f"Issues ({len(report['issues'])}):"])
    for issue in report["issues"]:
        entity_id = f" {issue['id']}" if "id" in issue else ""
        lines.append(f"- [{issue['severity']}] {issue['entity']}{entity_id}: {issue['message']}")

    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect an IFC/BIM model and emit a small report.")
    parser.add_argument("ifc_file", help="Path to an IFC file.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human-readable report.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--small-area-threshold",
        type=float,
        default=SMALL_AREA_THRESHOLD,
        help="Area below this value is flagged as unusually small. Default: 1.0",
    )
    args = parser.parse_args(argv)

    try:
        report = inspect_ifc_model(args.ifc_file, small_area_threshold=args.small_area_threshold)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        indent = 2 if args.pretty else None
        print(json.dumps(report, ensure_ascii=False, indent=indent))
    else:
        print(_human_summary(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
