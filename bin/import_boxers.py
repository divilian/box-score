#!/usr/bin/env python3
"""Import a JSON array of Box Score boxer profiles into MongoDB."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from bson import BSON, Decimal128, ObjectId, json_util
from bson.errors import InvalidDocument, InvalidId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from init_db import BOXER_SCHEMA


MANAGED_FIELDS = {"_id", "created_at", "updated_at"}
BOXER_DEFAULTS = {"published": False, "fight_history_complete": False}
BSON_TYPES = {
    "objectId": (ObjectId,),
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "date": (datetime,),
    "bool": (bool,),
    "int": (int,),
    "long": (int,),
    "double": (float,),
    "decimal": (Decimal128,),
}


def validate(value, schema, path="boxer"):
    """Check the constraints used by BOXER_SCHEMA without writing a document."""
    types = schema["bsonType"]
    if isinstance(types, str):
        types = [types]
    if not any(
        isinstance(value, BSON_TYPES[kind])
        and (not isinstance(value, bool) or kind == "bool")
        for kind in types
    ):
        raise ValueError(f"{path} must be {' or '.join(types)}")

    if "minLength" in schema and len(value.strip()) < schema["minLength"]:
        raise ValueError(f"{path} must not be blank")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{path} must be at least {schema['minimum']}")

    for field in schema.get("required", ()):
        if field not in value:
            raise ValueError(f"{path}.{field} is required")
    for field, field_schema in schema.get("properties", {}).items():
        if field in value:
            validate(value[field], field_schema, f"{path}.{field}")
    if "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")


def describe(value):
    return json_util.dumps(value, sort_keys=True)


def decode_object(pairs):
    document = {}
    for field, value in pairs:
        if field in document:
            raise ValueError(f"duplicate JSON field: {field!r}")
        document[field] = value
    return json_util.object_hook(document)


def find_additions(stored, incoming, prefix=""):
    """Return missing values and their paths, or raise on a conflicting value."""
    additions = {}
    paths = []
    for field, value in incoming.items():
        path = f"{prefix}.{field}" if prefix else field
        if field not in stored:
            additions[field] = value
            paths.append(path)
            continue

        current = stored[field]
        if isinstance(current, dict) and isinstance(value, dict):
            nested, nested_paths = find_additions(current, value, path)
            if nested:
                additions[field] = {**current, **nested}
                paths.extend(nested_paths)
        elif describe(current) != describe(value):
            raise ValueError(
                f"{path} conflicts (stored {describe(current)}, "
                f"incoming {describe(value)})"
            )

    return additions, paths


def utc_now():
    # PyMongo stores dates at millisecond precision.
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


def validate_boxer(document):
    validate(document, BOXER_SCHEMA)
    for field in ("birth_date", "death_date"):
        if field in document and document[field].time() != datetime.min.time():
            raise ValueError(f"boxer.{field} must be at midnight UTC")
    BSON.encode(document)


def import_boxer(collection, incoming, dry_run, fill_missing):
    slug = incoming["slug"]
    stored = collection.find_one({"slug": slug})
    if stored is None:
        now = utc_now()
        document = {
            **BOXER_DEFAULTS,
            **incoming,
            "_id": ObjectId(),
            "created_at": now,
            "updated_at": now,
        }
        validate_boxer(document)
        if not dry_run:
            collection.insert_one(document)
        return "inserted", ""

    additions, paths = find_additions(stored, incoming)
    if not additions:
        return "unchanged", ""
    document = {**stored, **additions, "updated_at": utc_now()}
    validate_boxer(document)
    if not fill_missing:
        return "unchanged", f"missing fields (use --fill-missing): {', '.join(paths)}"

    if not dry_run:
        # Compare the whole document so a concurrent edit (including a
        # manual edit without a timestamp change) can't be overwritten.
        result = collection.replace_one(
            {
                "_id": stored["_id"],
                "$expr": {"$eq": ["$$ROOT", {"$literal": stored}]},
            },
            document,
        )
        if not result.matched_count:
            raise ValueError("boxer changed during import; rerun the import")
    return "updated", f"added {', '.join(paths)}"


def require_slug_index(collection):
    for index in collection.list_indexes():
        if (
            list(index["key"].items()) == [("slug", 1)]
            and index.get("unique")
            and not index.get("sparse")
            and "partialFilterExpression" not in index
        ):
            return
    raise ValueError("missing unique boxers.slug index; run bin/init_db.py first")


def get_slug(value):
    if isinstance(value, dict):
        slug = value.get("slug")
        if isinstance(slug, str) and slug.strip():
            return slug
    return None


def import_records(collection, records, dry_run, fill_missing):
    slug_counts = Counter(get_slug(record) for record in records)
    counts = dict.fromkeys(("inserted", "updated", "unchanged", "rejected"), 0)
    for row, record in enumerate(records, start=1):
        slug = get_slug(record)
        label = f"record {row}"
        if slug is not None:
            label += f" ({slug!r})"

        try:
            if not isinstance(record, dict):
                raise ValueError("expected a JSON object")
            if slug is None:
                raise ValueError("slug must be a nonblank string")
            if slug_counts[slug] > 1:
                raise ValueError("slug appears more than once in the input file")
            managed = MANAGED_FIELDS.intersection(record)
            if managed:
                fields = ", ".join(sorted(managed))
                raise ValueError(f"omit importer-managed fields: {fields}")
            if "key" in record:
                raise ValueError("boxers are identified by slug; omit key")
            status, detail = import_boxer(collection, record, dry_run, fill_missing)
        except DuplicateKeyError:
            status, detail = "rejected", "duplicate key; rerun if the boxer was just added"
        except WriteError as exc:
            status, detail = "rejected", str((exc.details or {}).get("errmsg", exc))
        except (ValueError, OverflowError, InvalidDocument) as exc:
            status, detail = "rejected", str(exc)

        counts[status] += 1
        if dry_run and status in {"inserted", "updated"}:
            status = f"would be {status}"
        print(f"{label}: {status}" + (f" ({detail})" if detail else ""))

    heading = "Dry run" if dry_run else "Import"
    summary = ", ".join(f"{count} {status}" for status, count in counts.items())
    print(f"{heading}: {summary}")
    return 1 if counts["rejected"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filename", type=Path, help="JSON file containing an array of boxers")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen without writing")
    parser.add_argument("--fill-missing", action="store_true",
                        help="add absent fields to existing boxers")
    args = parser.parse_args()

    try:
        text = args.filename.read_text(encoding="utf-8")
        records = json.loads(text, object_pairs_hook=decode_object)
        if not isinstance(records, list):
            raise ValueError("expected a top-level JSON array")
    except (OSError, ValueError, TypeError, ArithmeticError, InvalidId, KeyError) as exc:
        print(f"Cannot read {args.filename}: {exc}", file=sys.stderr)
        return 2

    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
            collection = client["boxing"]["boxers"]
            if not args.dry_run and not collection.write_concern.acknowledged:
                raise ValueError("MongoDB connection must acknowledge writes")
            require_slug_index(collection)
            return import_records(collection, records, args.dry_run, args.fill_missing)
    except ValueError as exc:
        print(f"Import stopped: {exc}", file=sys.stderr)
    except PyMongoError as exc:
        print(f"Import stopped due to a MongoDB error ({type(exc).__name__}).",
              file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
