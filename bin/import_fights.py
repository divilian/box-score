#!/usr/bin/env python3
"""Import a JSON array of Box Score fights into MongoDB."""

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys

from bson import BSON, ObjectId
from bson.errors import InvalidDocument, InvalidId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from import_boxers import MANAGED_FIELDS, decode_object, find_additions, utc_now, validate
from init_db import FIGHT_SCHEMA


def is_suffixed_key(key, base_key):
    return re.fullmatch(re.escape(base_key) + r"-(?:[2-9]|[1-9][0-9]+)", key)


def validate_fight(document):
    validate(document, FIGHT_SCHEMA, "fight")
    if document["date"].time() != datetime.min.time():
        raise ValueError("fight.date must be at midnight UTC")

    participants = document["participants"]
    if len(participants) != 2:
        raise ValueError("fight.participants must contain exactly two boxers")
    slugs = tuple(sorted(participant["boxer_slug"] for participant in participants))
    if slugs[0] == slugs[1]:
        raise ValueError("fight.participants must contain two distinct boxer slugs")

    # The shared validator handles types and required fields, but does not
    # check array lengths or enum values.
    result = document["result"]
    outcomes = FIGHT_SCHEMA["properties"]["result"]["properties"]["outcome"]["enum"]
    if result["outcome"] not in outcomes:
        raise ValueError(f"fight.result.outcome must be one of {', '.join(outcomes)}")
    if result["outcome"] == "win":
        if result.get("winner_slug") not in slugs:
            raise ValueError("fight.result.winner_slug must identify one of the participants")
    elif "winner_slug" in result:
        raise ValueError("fight.result.winner_slug must be omitted for draws and no-contests")

    video_schema = FIGHT_SCHEMA["properties"]["videos"]["items"]
    video_types = video_schema["properties"]["type"]["enum"]
    for index, video in enumerate(document.get("videos", [])):
        if "type" in video and video["type"] not in video_types:
            raise ValueError(f"fight.videos[{index}].type must be one of {', '.join(video_types)}")

    BSON.encode(document)
    return slugs


def prepare_fight(record):
    if not isinstance(record, dict):
        raise ValueError("expected a JSON object")
    managed = MANAGED_FIELDS.intersection(record)
    if managed:
        fields = ", ".join(sorted(managed))
        raise ValueError(f"omit importer-managed fields: {fields}")

    now = utc_now()
    document = {
        "key": "(generated)",
        **record,
        "_id": ObjectId(),
        "created_at": now,
        "updated_at": now,
    }
    slugs = validate_fight(document)
    base_key = "-".join((document["date"].date().isoformat(), *slugs))
    if "key" not in record:
        document["key"] = base_key
    return document, slugs, base_key


def require_boxers(boxers, slugs):
    found = {
        boxer["slug"]
        for boxer in boxers.find({"slug": {"$in": list(slugs)}}, {"slug": 1})
    }
    missing = sorted(set(slugs) - found)
    if missing:
        raise ValueError(f"unknown boxer slug(s): {', '.join(missing)}")


def fight_additions(stored, incoming, slugs):
    # Compare the participants by slug and preserve their stored array order.
    participants = {
        participant["boxer_slug"]: participant for participant in incoming["participants"]
    }
    stored_slugs = tuple(sorted(p["boxer_slug"] for p in stored["participants"]))
    if stored_slugs != slugs:
        raise ValueError(f"participants conflict (stored {stored_slugs}, incoming {slugs})")

    fields = {
        field: value for field, value in incoming.items()
        if field not in MANAGED_FIELDS and field != "participants"
    }
    additions, paths = find_additions(stored, fields)
    updated_participants = []
    for participant in stored["participants"]:
        slug = participant["boxer_slug"]
        extra, added_paths = find_additions(
            participant, participants[slug], f"participants[{slug}]",
        )
        updated_participants.append({**participant, **extra})
        paths.extend(added_paths)

    if updated_participants != stored["participants"]:
        additions["participants"] = updated_participants
    return additions, paths


def import_fight(fights, boxers, incoming, slugs, base_key, explicit_key,
                 dry_run, fill_missing):
    key = incoming["key"]
    stored = fights.find_one({"key": key})
    require_boxers(boxers, slugs)

    if not explicit_key or (stored is None and key == base_key):
        same_day = fights.find({
            "key": {"$ne": key},
            "date": incoming["date"],
            "participants.boxer_slug": {"$all": list(slugs)},
        }, {"key": 1})
        for other in same_day:
            if explicit_key and is_suffixed_key(other["key"], base_key):
                continue
            raise ValueError(
                f"same-date bout exists under {other['key']!r}; "
                "supply the existing key or an explicit suffix for a separate bout"
            )

    if stored is None:
        if key != base_key and not is_suffixed_key(key, base_key):
            raise ValueError(f"new fight key must be {base_key!r} or use a suffix of -2 or higher")
        if not dry_run:
            fights.insert_one(incoming)
        return "inserted", ""

    additions, paths = fight_additions(stored, incoming, slugs)
    if not additions:
        return "unchanged", ""
    document = {**stored, **additions, "updated_at": utc_now()}
    validate_fight(document)
    if not fill_missing:
        return "unchanged", f"missing fields (use --fill-missing): {', '.join(paths)}"

    if not dry_run:
        # Guard against concurrent edits, including edits made without
        # changing updated_at.
        result = fights.replace_one(
            {
                "_id": stored["_id"],
                "$expr": {"$eq": ["$$ROOT", {"$literal": stored}]},
            },
            document,
        )
        if not result.matched_count:
            raise ValueError("fight changed during import; rerun the import")
    return "updated", f"added {', '.join(paths)}"


def require_key_index(fights):
    for index in fights.list_indexes():
        if (
            list(index["key"].items()) == [("key", 1)]
            and index.get("unique")
            and not index.get("sparse")
            and "partialFilterExpression" not in index
        ):
            return
    raise ValueError("missing unique fights.key index; run bin/init_db.py first")


def import_records(fights, boxers, records, dry_run, fill_missing):
    prepared = []
    key_counts = Counter()
    bout_counts = Counter()
    for record in records:
        try:
            document, slugs, base_key = prepare_fight(record)
        except (ValueError, OverflowError, InvalidDocument) as exc:
            prepared.append(str(exc))
            continue
        prepared.append((document, slugs, base_key, "key" in record))
        key_counts[document["key"]] += 1
        bout_counts[(document["date"], slugs)] += 1

    counts = dict.fromkeys(("inserted", "updated", "unchanged", "rejected"), 0)
    for row, item in enumerate(prepared, start=1):
        label = f"record {row}"
        try:
            if isinstance(item, str):
                raise ValueError(item)
            incoming, slugs, base_key, explicit_key = item
            key = incoming["key"]
            label += f" ({key!r})"
            if key_counts[key] > 1:
                raise ValueError("fight key appears more than once in the input file")
            if not explicit_key and bout_counts[(incoming["date"], slugs)] > 1:
                raise ValueError("same-date bouts in the input file require explicit keys")
            status, detail = import_fight(
                fights, boxers, incoming, slugs, base_key, explicit_key,
                dry_run, fill_missing,
            )
        except DuplicateKeyError:
            status, detail = "rejected", "duplicate key; rerun if the fight was just added"
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
    parser.add_argument("filename", type=Path, help="JSON file containing an array of fights")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen without writing")
    parser.add_argument("--fill-missing", action="store_true",
                        help="add absent fields to existing fights")
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
            db = client["boxing"]
            if not args.dry_run and not db.fights.write_concern.acknowledged:
                raise ValueError("MongoDB connection must acknowledge writes")
            require_key_index(db.fights)
            return import_records(db.fights, db.boxers, records, args.dry_run, args.fill_missing)
    except ValueError as exc:
        print(f"Import stopped: {exc}", file=sys.stderr)
    except PyMongoError as exc:
        print(f"Import stopped due to a MongoDB error ({type(exc).__name__}).",
              file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
