"""
Install and run:
python3 -m pip install "pymongo[srv]"
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
DATABASE_NAME = "notification_demo"
COLLECTION_NAME = "notifications"


def load_mongodb_uri() -> str:
    mongodb_uri = os.getenv("MONGODB_URI")
    if mongodb_uri:
        return mongodb_uri

    # A tiny local config file is a convenient fallback for quick experiments.
    # Expected shape: { "MONGODB_URI": "mongodb+srv://..." }
    if CONFIG_FILE.exists():
        parsed_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        config_uri = parsed_config.get("MONGODB_URI")
        if isinstance(config_uri, str) and config_uri:
            return config_uri

    raise RuntimeError(
        f"Missing MONGODB_URI. Set it in your environment or add it to {CONFIG_FILE.name}."
    )


def build_seed_documents() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)

    # The timestamps are intentionally different so sorting by recency is easy to see.
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
    mongodb_uri = load_mongodb_uri()
    client: MongoClient[dict[str, Any]] | None = None

    try:
        print("1. Connecting to MongoDB Atlas...")
        client = MongoClient(mongodb_uri, server_api=ServerApi("1"))

        # A ping confirms both connectivity and credentials before we do any writes.
        client.admin.command("ping")
        print("   Connected successfully.")

        database = client[DATABASE_NAME]
        collection: Collection[dict[str, Any]] = database[COLLECTION_NAME]
        print(f'2. Using database "{DATABASE_NAME}" and collection "{COLLECTION_NAME}".')

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
