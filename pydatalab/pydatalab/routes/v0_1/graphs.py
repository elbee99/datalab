from typing import Callable, Dict, Optional, Set

from flask import jsonify, request

from pydatalab.mongo import flask_mongo
from pydatalab.routes.utils import get_default_permissions


def get_graph_cy_format(item_id: Optional[str] = None, collection_id: Optional[str] = None):

    collection_id = request.args.get("collection_id", type=str)

    if item_id is None:
        if collection_id is not None:
            collection_immutable_id = flask_mongo.db.collections.find_one(
                {"collection_id": collection_id}, projection={"_id": 1}
            )
            if not collection_immutable_id:
                raise RuntimeError("No collection {collection_id=} found.")
            collection_immutable_id = collection_immutable_id["_id"]
            query = {
                "$and": [
                    {"relationships.immutable_id": collection_immutable_id},
                    {"relationships.type": "collections"},
                ]
            }
        else:
            query = {}
        all_documents = flask_mongo.db.items.find(
            {**query, **get_default_permissions(user_only=False)},
            projection={"item_id": 1, "name": 1, "type": 1, "relationships": 1},
        )
        node_ids: Set[str] = {document["item_id"] for document in all_documents}
        all_documents.rewind()

    else:
        all_documents = list(
            flask_mongo.db.items.find(
                {
                    "$or": [{"item_id": item_id}, {"relationships.item_id": item_id}],
                    **get_default_permissions(user_only=False),
                },
                projection={"item_id": 1, "name": 1, "type": 1, "relationships": 1},
            )
        )

        node_ids = {document["item_id"] for document in all_documents} | {
            relationship["item_id"]
            for document in all_documents
            for relationship in document.get("relationships", [])
        }
        if len(node_ids) > 1:
            or_query = [{"item_id": id} for id in node_ids if id != item_id]
            # query.extend([{"relationships.item_id": id} for id in node_ids if id != item_id])
            next_shell = flask_mongo.db.items.find(
                {
                    "$or": or_query,
                    **get_default_permissions(user_only=False),
                },
                projection={"item_id": 1, "name": 1, "type": 1, "relationships": 1},
            )

            all_documents.extend(next_shell)
            node_ids = node_ids | {document["item_id"] for document in all_documents}

    nodes = []
    edges = []

    # Collect the elements that have already been added to the graph, to avoid duplication
    drawn_elements = set()
    for document in all_documents:

        node_collections = set()
        for relationship in document.get("relationships", []):
            # only considering child-parent relationships
            if relationship.get("type") == "collections" and not collection_id:
                collection_data = flask_mongo.db.collections.find_one(
                    {
                        "_id": relationship["immutable_id"],
                        **get_default_permissions(user_only=False),
                    },
                    projection={"collection_id": 1, "title": 1, "type": 1},
                )
                if collection_data:
                    if relationship["immutable_id"] not in node_collections:
                        nodes.append(
                            {
                                "data": {
                                    "id": f'Collection: {collection_data["collection_id"]}',
                                    "name": collection_data["title"],
                                    "type": collection_data["type"],
                                    "shape": "triangle",
                                }
                            }
                        )
                        node_collections.add(relationship["immutable_id"])
                    source = f'Collection: {collection_data["collection_id"]}'
                    target = document.get("item_id")
                    edges.append(
                        {
                            "data": {
                                "id": f"{source}->{target}",
                                "source": source,
                                "target": target,
                                "value": 1,
                            }
                        }
                    )
                continue

            if relationship.get("relation") not in ("parent", "is_part_of"):
                continue

            target = document["item_id"]
            source = relationship["item_id"]
            if source not in node_ids:
                continue
            edge_id = f"{source}->{target}"
            if edge_id not in drawn_elements:
                drawn_elements.add(edge_id)
                edges.append(
                    {
                        "data": {
                            "id": edge_id,
                            "source": source,
                            "target": target,
                            "value": 1,
                        }
                    }
                )

        if document["item_id"] not in drawn_elements:
            drawn_elements.add(document["item_id"])
            nodes.append(
                {
                    "data": {
                        "id": document["item_id"],
                        "name": document["name"],
                        "type": document["type"],
                    }
                }
            )

    # We want to filter out all the starting materials that don't have relationships since there are so many of them:
    whitelist = {edge["data"]["source"] for edge in edges}

    nodes = [
        node
        for node in nodes
        if node["data"]["type"] in ("samples", "cells") or node["data"]["id"] in whitelist
    ]

    return (jsonify(status="success", nodes=nodes, edges=edges), 200)


get_graph_cy_format.methods = ("GET",)  # type: ignore


ENDPOINTS: Dict[str, Callable] = {
    "/item-graph/<item_id>": get_graph_cy_format,
    "/item-graph": get_graph_cy_format,
}
