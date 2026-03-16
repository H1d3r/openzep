from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, create_model


ENTITY_RESERVED_FIELDS = {
    "uuid",
    "name",
    "group_id",
    "name_embedding",
    "summary",
    "created_at",
}

_PROPERTY_TYPE_MAP: dict[str, type[Any]] = {
    "text": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "boolean": bool,
    "bool": bool,
}


@dataclass
class CompiledOntology:
    entity_types: dict[str, type[BaseModel]]
    edge_types: dict[str, type[BaseModel]]
    edge_type_map: dict[tuple[str, str], list[str]]
    entity_type_names: set[str]


_graph_ontologies: dict[str, CompiledOntology] = {}
_user_ontologies: dict[str, CompiledOntology] = {}
_default_ontology: CompiledOntology | None = None


def _normalize_property_name(name: str, *, is_entity: bool) -> str:
    normalized = (name or "").strip()
    if not normalized:
        return "value"
    if is_entity and normalized.lower() in ENTITY_RESERVED_FIELDS:
        return f"entity_{normalized}"
    return normalized


def _create_dynamic_model(
    name: str,
    description: str,
    properties: list[dict[str, Any]],
    *,
    is_entity: bool,
) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Field]] = {}
    for prop in properties:
        prop_name = _normalize_property_name(str(prop.get("name", "value")), is_entity=is_entity)
        prop_type = str(prop.get("type", "Text")).lower()
        python_type = _PROPERTY_TYPE_MAP.get(prop_type, str)
        prop_desc = str(prop.get("description", prop_name))
        fields[prop_name] = (python_type | None, Field(default=None, description=prop_desc))

    model = create_model(name, __base__=BaseModel, **fields)
    model.__doc__ = description or f"{name} schema"
    return model


def compile_ontology(
    entity_types: list[dict[str, Any]] | None,
    edge_types: list[dict[str, Any]] | None,
) -> CompiledOntology:
    compiled_entities: dict[str, type[BaseModel]] = {}
    compiled_edges: dict[str, type[BaseModel]] = {}
    edge_type_map: dict[tuple[str, str], list[str]] = {}

    for entity in entity_types or []:
        entity_name = str(entity.get("name", "")).strip()
        if not entity_name:
            continue
        compiled_entities[entity_name] = _create_dynamic_model(
            entity_name,
            str(entity.get("description", "")),
            list(entity.get("properties", []) or []),
            is_entity=True,
        )

    for edge in edge_types or []:
        edge_name = str(edge.get("name", "")).strip()
        if not edge_name:
            continue
        compiled_edges[edge_name] = _create_dynamic_model(
            edge_name,
            str(edge.get("description", "")),
            list(edge.get("properties", []) or []),
            is_entity=False,
        )
        for source_target in edge.get("source_targets", []) or []:
            source = str(source_target.get("source", "Entity")).strip() or "Entity"
            target = str(source_target.get("target", "Entity")).strip() or "Entity"
            edge_type_map.setdefault((source, target), []).append(edge_name)

    if compiled_edges and not edge_type_map:
        edge_type_map[("Entity", "Entity")] = list(compiled_edges.keys())

    return CompiledOntology(
        entity_types=compiled_entities,
        edge_types=compiled_edges,
        edge_type_map=edge_type_map,
        entity_type_names=set(compiled_entities.keys()),
    )


def set_ontology(
    *,
    graph_ids: list[str] | None,
    user_ids: list[str] | None,
    entity_types: list[dict[str, Any]] | None,
    edge_types: list[dict[str, Any]] | None,
) -> CompiledOntology:
    global _default_ontology

    compiled = compile_ontology(entity_types, edge_types)

    for graph_id in graph_ids or []:
        if graph_id:
            _graph_ontologies[graph_id] = compiled

    for user_id in user_ids or []:
        if user_id:
            _user_ontologies[user_id] = compiled

    if not (graph_ids or user_ids):
        _default_ontology = compiled

    return compiled


def get_ontology(graph_id: str | None = None, user_id: str | None = None) -> CompiledOntology | None:
    if graph_id and graph_id in _graph_ontologies:
        return _graph_ontologies[graph_id]
    if user_id and user_id in _user_ontologies:
        return _user_ontologies[user_id]
    return _default_ontology
