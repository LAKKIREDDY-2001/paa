"""
Install and run:
python3 -m pip install pymongo
export MONGODB_URI="your-mongodb-atlas-connection-string"
python3 mongodbExample.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi

CONFIG_FILE = Path(__file__).with_name("mongodb.config.json")
DEFAULT_DATABASE_NAME = "notification_demo"
DEFAULT_COLLECTION_NAME = "notifications"


def is_placeholder_uri(uri: str) -> bool:
    return "USERNAME" in uri or "NEW_PASSWORD" in uri


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}

    parsed_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(parsed_config, dict):
        raise RuntimeError(f"{CONFIG_FILE.name} must contain a JSON object.")
    return parsed_config


def load_mongodb_uri(config: dict[str, Any]) -> str:
    mongodb_uri = os.getenv("MONGODB_URI")
    if mongodb_uri:
        if is_placeholder_uri(mongodb_uri):
            raise RuntimeError(
                "MONGODB_URI still contains placeholder values. Replace USERNAME and NEW_PASSWORD with your Atlas credentials."
            )
        return mongodb_uri

    # The local config file supports either:
    # { "MONGODB_URI": "mongodb+srv://..." }
    # or
    # { "uri": "mongodb+srv://..." }
    for key in ("MONGODB_URI", "uri"):
        config_uri = config.get(key)
        if isinstance(config_uri, str) and config_uri.strip():
            if is_placeholder_uri(config_uri):
                raise RuntimeError(
                    f"{CONFIG_FILE.name} still contains placeholder values. Replace USERNAME and NEW_PASSWORD with your Atlas credentials."
                )
            return config_uri

    raise RuntimeError(
        f"Missing MONGODB_URI. Set it in your environment or add MONGODB_URI or uri to {CONFIG_FILE.name}."
    )


def load_database_name(config: dict[str, Any]) -> str:
    config_database = config.get("database")
    if isinstance(config_database, str) and config_database.strip():
        return config_database
    return DEFAULT_DATABASE_NAME


def load_collection_name(config: dict[str, Any]) -> str:
    config_collection = config.get("collection")
    if isinstance(config_collection, str) and config_collection.strip():
        return config_collection
    return DEFAULT_COLLECTION_NAME


def build_seed_documents() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)

    # Different timestamps make the "most recent" query easy to verify.
    return [
        {
            "user_id": "user_001",
            "channel": "email",
            "title": "Welcome to PriceAlerter",
            "message": "Your account is ready and your first alert is active.",
            "status": "sent",
            "created_at": now - timedelta(days=10),
        },
        {
            "user_id": "user_002",
            "channel": "push",
            "title": "Price dropped on AirPods Pro 2",
            "message": "The item is now below your target price.",
            "status": "sent",
            "created_at": now - timedelta(days=9),
        },
        {
            "user_id": "user_003",
            "channel": "sms",
            "title": "Alert failed to deliver",
            "message": "We could not reach the saved phone number.",
            "status": "failed",
            "created_at": now - timedelta(days=8),
        },
        {
            "user_id": "user_004",
            "channel": "email",
            "title": "Weekly watchlist summary",
            "message": "Three products moved closer to your target price.",
            "status": "sent",
            "created_at": now - timedelta(days=7),
        },
        {
            "user_id": "user_005",
            "channel": "push",
            "title": "Restock notice",
            "message": "A tracked product is back in stock at Flipkart.",
            "status": "queued",
            "created_at": now - timedelta(days=6),
        },
        {
            "user_id": "user_006",
            "channel": "email",
            "title": "Cart reminder",
            "message": "Your saved deal is still available at the discounted price.",
            "status": "sent",
            "created_at": now - timedelta(days=5),
        },
        {
            "user_id": "user_007",
            "channel": "push",
            "title": "Large price drop detected",
            "message": "The product fell 18 percent since yesterday.",
            "status": "sent",
            "created_at": now - timedelta(days=4),
        },
        {
            "user_id": "user_008",
            "channel": "email",
            "title": "Alert paused",
            "message": "We paused duplicate notifications for the same product.",
            "status": "paused",
            "created_at": now - timedelta(days=3),
        },
        {
            "user_id": "user_009",
            "channel": "sms",
            "title": "Target reached",
            "message": "Your tracked washing machine hit the exact target price.",
            "status": "sent",
            "created_at": now - timedelta(days=2),
        },
        {
            "user_id": "user_010",
            "channel": "push",
            "title": "New deal recommendation",
            "message": "Based on your watchlist, you may like this new iPad discount.",
            "status": "queued",
            "created_at": now - timedelta(days=1),
        },
    ]


def main() -> None:
    config = load_config()
    mongodb_uri = load_mongodb_uri(config)
    database_name = load_database_name(config)
    collection_name = load_collection_name(config)
    client: MongoClient[dict[str, Any]] | None = None

    try:
        print("1. Connecting to MongoDB Atlas...")
        client = MongoClient(mongodb_uri, server_api=ServerApi("1"))

        # A ping confirms the cluster is reachable before we write any data.
        client.admin.command("ping")
        print("   Connected successfully.")

        database = client[database_name]
        collection: Collection[dict[str, Any]] = database[collection_name]
        print(f'2. Using database "{database_name}" and collection "{collection_name}".')

        documents = build_seed_documents()
        print(f"3. Inserting {len(documents)} realistic notification documents...")
        insert_result = collection.insert_many(documents)
        print(f"   Inserted {len(insert_result.inserted_ids)} documents.")

        print("4. Reading the 5 most recent full documents...")
        most_recent_documents = list(
            collection.find().sort("created_at", -1).limit(5)
        )
        for document in most_recent_documents:
            print(document)

        example_id = insert_result.inserted_ids[0]
        print(f"5. Reading one full document by _id: {example_id}")
        one_document = collection.find_one({"_id": example_id})
        print(one_document)

    except (PyMongoError, RuntimeError, ValueError, OSError) as error:
        print("MongoDB example failed.")
        print(error)
        raise SystemExit(1) from error
    finally:
        if client is not None:
            print("6. Closing the MongoDB connection...")
            client.close()
            print("   Connection closed.")


if __name__ == "__main__":
    main()
