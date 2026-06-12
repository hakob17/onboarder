"""AI guided tours: an LLM-authored onboarding walkthrough of the workspace
graph. Steps reference real node ids (validated) and drive the map like chat's
focus_view directives."""

import json

from pydantic import BaseModel

from ..config import MODEL
from ..db import get_conn, now, row_to_dict


class TourStep(BaseModel):
    title: str
    narration: str
    node_ids: list[str]
    mode: str  # highlight | trace | isolate


class TourPlan(BaseModel):
    title: str
    steps: list[TourStep]


PROMPT = """You are creating a guided onboarding tour of a codebase for someone seeing it for \
the first time (developers and non-technical teammates). Below is the system graph: every node \
id with its kind and name, then the edges between them.

Write a tour of 5-7 steps. Rules:
- Each step has a short title, 1-3 sentences of plain-language narration (business meaning first), \
and the node_ids it should light up on the map. Use ONLY node ids from the inventory.
- mode "trace" for end-to-end flows (order node_ids along the path), "highlight" for groups, \
"isolate" to focus on one area.
- A good arc: what the system is → the most important end-to-end flow → where the data lives \
(tables, who writes/reads) → how the projects call each other (cross-project) → one gotcha or \
notable detail worth knowing on day one.

NODES:
{nodes}

EDGES:
{edges}"""


def _inventory(workspace_id: str) -> tuple[str, str, set[str]]:
    conn = get_conn()
    try:
        node_rows = conn.execute(
            "SELECT id, kind, name FROM nodes WHERE workspace_id = ? ORDER BY kind, name LIMIT 180",
            (workspace_id,)).fetchall()
        edge_rows = conn.execute(
            "SELECT src, dst, kind FROM edges WHERE workspace_id = ? LIMIT 200",
            (workspace_id,)).fetchall()
        cross_rows = conn.execute(
            "SELECT src, dst, kind FROM cross_edges WHERE workspace_id = ? AND status != 'rejected'",
            (workspace_id,)).fetchall()
    finally:
        conn.close()
    ids = {r["id"] for r in node_rows}
    nodes = "\n".join(f"{r['id']} | {r['kind']} | {r['name']}" for r in node_rows)
    edges = "\n".join(f"{r['src']} -{r['kind']}-> {r['dst']}" for r in [*edge_rows, *cross_rows])
    return nodes, edges, ids


def generate_tour(workspace_id: str) -> dict:
    from . import get_client

    nodes, edges, known_ids = _inventory(workspace_id)
    if not known_ids:
        raise ValueError("workspace has no graph yet")
    client = get_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": PROMPT.format(nodes=nodes, edges=edges)}],
        output_format=TourPlan,
    )
    plan = response.parsed_output

    steps = []
    for step in plan.steps:
        valid_ids = [i for i in step.node_ids if i in known_ids]
        if not valid_ids:
            continue
        mode = step.mode if step.mode in ("highlight", "trace", "isolate") else "highlight"
        steps.append({"title": step.title, "narration": step.narration,
                      "node_ids": valid_ids, "mode": mode})
    if len(steps) < 3:
        raise ValueError("model produced too few grounded steps; try again")

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO tours(workspace_id, title, steps, created_at) VALUES(?,?,?,?)",
            (workspace_id, plan.title, json.dumps(steps), now()))
        conn.commit()
        tour_id = cur.lastrowid
    finally:
        conn.close()
    return {"id": tour_id, "title": plan.title, "steps": steps}


def list_tours(workspace_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, steps, created_at FROM tours WHERE workspace_id = ?"
            " ORDER BY id DESC LIMIT 10", (workspace_id,)).fetchall()
        return [row_to_dict(r, ("steps",)) for r in rows]
    finally:
        conn.close()
