#!/usr/bin/env python3
# init_db.py: Create/update Box Score's collections, validators, and indexes.

import os

from pymongo import ASCENDING, MongoClient


# MongoDB's $jsonSchema uses BSON types, rather than Python types.
STRING = {"bsonType": "string"}
NONEMPTY_STRING = {"bsonType": "string", "minLength": 1}
DATE = {"bsonType": "date"}
BOOLEAN = {"bsonType": "bool"}
COUNT = {"bsonType": ["int", "long"], "minimum": 0}
NUMBER = {"bsonType": ["int", "long", "double", "decimal"]}


def array_of(items, **constraints):
    return {"bsonType": "array", "items": items, **constraints}


def object_schema(properties, required=()):
    schema = {"bsonType": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


RECORD_FIELDS = {
    field: COUNT for field in ("wins", "losses", "draws", "no_contests")
}
SOURCE = object_schema({
    "url": STRING,
    "title": STRING,
    "publisher": STRING,
    "accessed_on": DATE,
    "supports": array_of(STRING),
    "notes": STRING,
    "additionalProperties": False
})
COMMON_FIELDS = {
    "_id": {"bsonType": "objectId"},
    "sources": array_of(SOURCE),
    "created_at": DATE,
    "updated_at": DATE,
}

BOXER_SCHEMA = object_schema({
    **COMMON_FIELDS,
    "name": NONEMPTY_STRING,
    "slug": NONEMPTY_STRING,
    "birth_name": STRING,
    "nicknames": array_of(STRING),
    "birth_date": DATE,
    "death_date": DATE,
    "birth_place": STRING,
    "nationality": STRING,
    "stance": STRING,
    "height_inches": NUMBER,
    "reach_inches": NUMBER,
    "weight_classes": array_of(STRING),
    "portrait": object_schema({
        "url": NONEMPTY_STRING,
        "source_url": STRING,
        "credit": STRING,
        "license": STRING,
    }, required=("url",)),
    "reported_career_record": object_schema({
        **RECORD_FIELDS,
        "as_of_date": DATE,
    }),
    "fight_history_complete": BOOLEAN,
    "published": BOOLEAN,
}, required=("_id", "name", "slug", "fight_history_complete", "published",
             "created_at", "updated_at"))

PARTICIPANT = object_schema({
    "boxer_slug": NONEMPTY_STRING,
    "name_at_fight": STRING,
    "weight_lb": {"bsonType": "decimal"},
    "pre_fight_record": object_schema(RECORD_FIELDS),
}, required=("boxer_slug",))

FIGHT_SCHEMA = object_schema({
    **COMMON_FIELDS,
    "key": NONEMPTY_STRING,
    "date": DATE,
    "participants": array_of(PARTICIPANT, minItems=2, maxItems=2),
    "weight_class": STRING,
    "scheduled_rounds": COUNT,
    "rounds_completed": COUNT,
    "result": object_schema({
        "outcome": {"bsonType": "string",
                    "enum": ["win", "draw", "no_contest"]},
        "winner_slug": NONEMPTY_STRING,
        "method": STRING,
        "round": {"bsonType": ["int", "long"], "minimum": 1},
        "time": STRING,
        "notes": STRING,
    }, required=("outcome",)),
    "titles_at_stake": array_of(STRING),
    "venue": STRING,
    "location": STRING,
    "videos": array_of(object_schema({
        "youtube_id": NONEMPTY_STRING,
        "type": {"bsonType": "string",
                 "enum": ["full_fight", "highlights", "other"]},
        "duration_seconds": COUNT,
        "verified": BOOLEAN,
        "last_checked_at": DATE,
    }, required=("youtube_id",))),
}, required=("_id", "key", "date", "participants", "result",
             "created_at", "updated_at"))

# (Cross-document references, immutable slugs, and relationships between
# participants and results are application-level checks.)


def ensure_collection(db, name, schema):
    """Create a collection or replace its validator without deleting data."""
    options = {
        "validator": {"$jsonSchema": schema},
        "validationLevel": "strict",
        "validationAction": "error",
    }
    if name in db.list_collection_names():
        # collMod changes collection settings in place. Existing documents
        # are not automatically revalidated by this operation.
        db.command("collMod", name, **options)
        print(f"Updated validator: {name}")
    else:
        db.create_collection(name, **options)
        print(f"Created collection: {name}")


def main():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    with MongoClient(uri) as client:
        db = client["boxing"]
        ensure_collection(db, "boxers", BOXER_SCHEMA)
        ensure_collection(db, "fights", FIGHT_SCHEMA)

        # create_index reuses an identical existing index. Conflicting
        # definitions or duplicate values raise errors rather than causing
        # us to drop an index or delete records automatically.
        db.boxers.create_index("slug", unique=True)
        db.boxers.create_index("weight_classes")
        db.fights.create_index("key", unique=True)
        db.fights.create_index([
            ("participants.boxer_slug", ASCENDING),
            ("date", ASCENDING),
        ])
        print("Box Score collections, validators, and indexes configured.")


if __name__ == "__main__":
    main()
