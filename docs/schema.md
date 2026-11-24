# Box Score — Data schema (draft v0.2)

**Status:** Proposed design, not an existing MongoDB validation rule.

Database: **`boxing`**  
Collections: **`boxers`**, **`fights`**

MongoDB does not require a fixed schema. This document describes our intended
application-level contract: field names, types, meanings, validation rules,
indexes, and decisions to revisit. We can implement a small set of MongoDB
validators later; the more involved cross-document checks belong in Python.

## Conventions

- **Required** means required for a valid Box Score record, not necessarily
  something MongoDB enforces automatically.
- **Optional** fields may be *omitted*. Unknown information is not guessed.
  `null` should be reserved for cases where it is deliberately useful to
  distinguish an explicitly unknown value from a field never supplied.
- Dates are stored as **BSON Date** values, even when they represent calendar
  dates without a time of day. Encode day-only dates at **00:00:00 UTC** and
  format them as UTC calendar dates so local time-zone conversion cannot
  inadvertently shift a fight or birth date.
- Numeric measurements use **inches** for height/reach and **pounds** for
  official weigh-in weights. Weights can contain fractional pounds.
- An immutable **string slug** links a fight participant to a boxer and
  serves as the boxer's import identity and public URL segment. MongoDB
  ObjectIds are internal document identifiers, not cross-document references.
- Source URLs and externally reported statistics are claims supported by
  references; they must not be silently replaced by calculations.
- Field naming uses `snake_case`.

## 1. Collection: `boxers`

One document per real boxer, including boxers who appear only as opponents
and do not yet have public pages.

| Field | Type | Required | Meaning / rules |
| --- | --- | :---: | --- |
| `_id` | ObjectId | Yes | MongoDB document identifier. |
| `name` | String | Yes | Canonical display name, e.g. `Muhammad Ali`. |
| `slug` | String | Yes | Unique, immutable boxer identifier and public URL segment, e.g. `muhammad-ali`; required even for unpublished records. |
| `birth_name` | String | No | Name at birth, when relevant; not a synonym for a longer version of `name`. |
| `nicknames` | Array of strings | No | Zero or more known nicknames. |
| `birth_date` | Date | No | Date of birth, if reliably known. |
| `death_date` | Date | No | Date of death, if applicable and known. |
| `birth_place` | String | No | Place of birth, as human-readable text. |
| `nationality` | String | No | Human-readable nationality. |
| `stance` | String | No | E.g. `orthodox`, `southpaw`, `switch`; unknown values omitted. |
| `height_inches` | Number | No | Height in inches, including fractions when reported. |
| `reach_inches` | Number | No | Reach in inches, including fractions when reported. |
| `weight_classes` | Array of strings | No | Standardized weight-class codes for **professional** bouts, used by the directory. |
| `portrait` | Object | No | External image and licensing metadata (below). |
| `reported_career_record` | Object | No | An independently sourced career/record snapshot, *not* a cached count of our fights. |
| `fight_history_complete` | Boolean | Yes | Curator-verified completeness; default `false`. |
| `published` | Boolean | Yes | Public profile/directory visibility; default `false`. |
| `sources` | Array of objects | No | References for claims in this document. |
| `created_at` | Date | Yes | Record creation timestamp. |
| `updated_at` | Date | Yes | Last modification timestamp. |

### `portrait` object (optional)

| Field | Type | Required if present | Meaning |
| --- | --- | :---: | --- |
| `url` | String | Yes | Image URL used by the browser. |
| `source_url` | String | No | Source page, such as Wikimedia Commons. |
| `credit` | String | No | Photographer / rights attribution. |
| `license` | String | No | License designation and attribution requirements. |

Only use images whose licenses permit the intended display, and preserve
attribution. We may choose to cache or host properly licensed portraits
later; no such storage is required for the prototype.

### `reported_career_record` object (optional)

| Field | Type | Meaning |
| --- | --- | --- |
| `wins` | Integer | Reported wins. |
| `losses` | Integer | Reported losses. |
| `draws` | Integer | Reported draws, if known. |
| `no_contests` | Integer | Reported no-contests, if known. |
| `as_of_date` | Date | Snapshot date if the record was not necessarily final. |

A separate `sources` entry should identify the reference for this claim.
Do not automatically overwrite this object with aggregated totals. The
reported record and a calculated record may differ while our fight coverage
is incomplete or sources disagree.

### Minimal unpublished boxer records

A boxer does **not** need a complete profile to exist in `boxers`. We can
create a record containing `slug`, `name`, `published: false`,
`fight_history_complete: false`, and timestamps, with optional biographical
facts as we learn them. Every participant in every fight should refer to a
boxer document, even if that boxer is unpublished.

The site's directory includes only `published: true` boxers. An opponent's
name becomes a hyperlink only when that opponent's boxer document is
published.

### Boxer example (MongoDB Extended JSON, illustrative)

This example shows how BSON ObjectIds and dates can be represented in a
portable JSON form. The identity and boxing facts are illustrative; research
sources still need to be documented before publication.

```json
{
  "_id": { "$oid": "64b000000000000000000001" },
  "name": "Muhammad Ali",
  "slug": "muhammad-ali",
  "birth_name": "Cassius Marcellus Clay Jr.",
  "nicknames": ["The Greatest", "The Louisville Lip"],
  "birth_date": { "$date": "1942-01-17T00:00:00Z" },
  "death_date": { "$date": "2016-06-03T00:00:00Z" },
  "birth_place": "Louisville, Kentucky, United States",
  "nationality": "American",
  "stance": "orthodox",
  "height_inches": 75,
  "reach_inches": 78,
  "weight_classes": ["heavyweight"],
  "reported_career_record": {
    "wins": 56,
    "losses": 5,
    "draws": 0,
    "no_contests": 0
  },
  "fight_history_complete": false,
  "published": true,
  "sources": [],
  "created_at": { "$date": "2026-11-22T00:00:00Z" },
  "updated_at": { "$date": "2026-11-22T00:00:00Z" }
}
```

The example omits `portrait` to demonstrate that an image is optional, even
for a published record. The example does **not** imply that the full Ali fight
history has already been entered; hence `fight_history_complete: false`.

## 2. Collection: `fights`

One document per professional bout, shared by **both** participants. No
"featured boxer" field and no duplicate document for the other perspective.

| Field | Type | Required | Meaning / rules |
| --- | --- | :---: | --- |
| `_id` | ObjectId | Yes | MongoDB document identifier. |
| `key` | String | Yes | Unique, immutable identifier for imports/upserts, generated using the fight-key convention below. |
| `date` | Date | Yes | Bout date as a UTC calendar date. |
| `participants` | Array of objects | Yes | Exactly two **distinct** boxer references (below). |
| `weight_class` | String | No | Standardized **official division for this bout**; do not infer from weights alone. |
| `scheduled_rounds` | Integer | No | Announced/planned number of rounds. |
| `rounds_completed` | Integer | No | Number of completed rounds, particularly useful for decisions. |
| `result` | Object | Yes | Outcome and method (below). |
| `titles_at_stake` | Array of strings | No | Identifiers / descriptions of any titles contested. |
| `venue` | String | No | Venue name. |
| `location` | String | No | Human-readable city/region/country. |
| `videos` | Array of objects | No | Candidate YouTube recordings (below). |
| `sources` | Array of objects | No | References for fight facts. |
| `created_at` | Date | Yes | Record creation timestamp. |
| `updated_at` | Date | Yes | Last modification timestamp. |

### Fight-key convention

Generate `key` automatically when a fight is first created, using the
UTC calendar date and the two participant slugs in ascending
lexicographic order:

```text
YYYY-MM-DD-<first-boxer-slug>-<second-boxer-slug>
```

For example, Ali–Frazier I has the key
`1971-03-08-joe-frazier-muhammad-ali`. Sorting the slugs ensures that
importing a bout from either boxer's perspective produces the same key.

If the same two boxers fought more than once on the same date, use a
numeric suffix (`-2`, `-3`, etc.) for additional bouts, assigned in
chronological order when known and consistently reused on subsequent
imports. The first bout uses the unsuffixed key. Resolve ambiguous
same-day bouts explicitly rather than guessing or creating duplicates.

Once assigned, a fight's key is immutable, even if its date is later
corrected. Imports of corrected bouts must reuse the existing key
rather than generate a new one.

### `participants` array (exactly two entries)

| Field | Type | Required | Meaning / rules |
| --- | --- | :---: | --- |
| `boxer_slug` | String | Yes | References `boxers.slug`; participants must differ. |
| `name_at_fight` | String | No | Historical name when different from the canonical boxer name. |
| `weight_lb` | Decimal128 | No | Official weigh-in weight in pounds; never invent a value. |
| `pre_fight_record` | Object | No | Independently reported pre-bout record (below). |

A `pre_fight_record` may contain integer `wins`, `losses`, `draws`, and
`no_contests`. A missing component means **unknown**, not automatically
zero. When the complete record is known, provide all four components; when
only W–L is reported, preserve that partial snapshot honestly.

Historical weigh-in weights can be fractions of a pound. Decimal128 is
preferred for exact decimal storage. For a JSON import file, represent it
using MongoDB Extended JSON (`{"$numberDecimal": "205.5"}`). Do not
substitute a boxer's typical, maximum, or in-ring weight for the official
weigh-in figure.

### `result` object

| Field | Type | Required | Meaning / rules |
| --- | --- | :---: | --- |
| `outcome` | String | Yes | One of `win`, `draw`, `no_contest` (extend later if needed). |
| `winner_slug` | String | If `outcome=win` | Must reference one of the two participants; omit for draws/no-contests. |
| `method` | String | No | Standardized code: `KO`, `TKO`, `UD`, `SD`, `MD`, `DQ`, `RTD`, `PTS`, `TD`, etc. |
| `round` | Integer | No | Round of a stoppage or other round-specific conclusion. |
| `time` | String | No | Time within that round, e.g. `2:10`. |
| `notes` | String | No | Unusual technical or historical details. |

`outcome` describes the **bout as a whole**, not the perspective of one
boxer. The application derives `W` or `L` by comparing the current boxer
with `winner_slug`; a draw or no-contest displays appropriately on both pages.

For example, a stoppage in round 3 can display as `W TKO3` / `L TKO3`.
For a decision after 15 completed rounds, display `W UD15` / `L UD15`.
Do not assume that `scheduled_rounds` necessarily equals completed rounds
in an unusual technical decision.

### `videos` array (optional)

| Field | Type | Required if entry present | Meaning |
| --- | --- | :---: | --- |
| `youtube_id` | String | Yes | Video identifier, not the full URL. |
| `type` | String | No | `full_fight`, `highlights`, or `other`. |
| `duration_seconds` | Integer | No | Runtime, if verified or retrieved. |
| `verified` | Boolean | No | Whether a reviewer confirmed the video's actual contents. |
| `last_checked_at` | Date | No | When availability/content was last checked. |

For the result hyperlink: prefer a **verified full fight**, breaking ties
by **shortest duration**; use verified highlights only if there is no
verified full fight and we want a fallback. Avoid automatically presenting
unverified matches as full recordings.

YouTube thumbnail URLs are **not stored**. Construct a thumbnail URL from
the stored YouTube ID when rendering the page and let the browser retrieve
it from YouTube's image host. Not every size is available for every video.

### `sources` array (both collections)

A flexible initial source entry may include:

| Field | Type | Meaning |
| --- | --- | --- |
| `url` | String | Original reference URL. |
| `title` | String | Page/article/book title. |
| `publisher` | String | Provider or publication. |
| `accessed_on` | Date | When consulted. |
| `supports` | Array of strings | Which facts this reference supports, e.g. `birth_date`, `result`, `weigh_in_weights`. |
| `notes` | String | Disagreement, uncertainty, or other context. |

We do **not** yet require field-level citations for every value. This is a
starting convention that can become more structured once we have experience
with real boxing sources.

### Fight example (MongoDB Extended JSON, illustrative)

Ali–Frazier I, shown from neither fighter's perspective. The slugs are
illustrative. The referenced
boxer documents must exist before importing the fight.

```json
{
  "_id": { "$oid": "64b000000000000000000003" },
  "key": "1971-03-08-joe-frazier-muhammad-ali",
  "date": { "$date": "1971-03-08T00:00:00Z" },
  "participants": [
    {
      "boxer_slug": "muhammad-ali",
      "weight_lb": { "$numberDecimal": "215" },
      "pre_fight_record": {
        "wins": 31,
        "losses": 0,
        "draws": 0,
        "no_contests": 0
      }
    },
    {
      "boxer_slug": "joe-frazier",
      "weight_lb": { "$numberDecimal": "205.5" },
      "pre_fight_record": {
        "wins": 26,
        "losses": 0,
        "draws": 0,
        "no_contests": 0
      }
    }
  ],
  "weight_class": "heavyweight",
  "scheduled_rounds": 15,
  "rounds_completed": 15,
  "result": {
    "outcome": "win",
    "winner_slug": "joe-frazier",
    "method": "UD"
  },
  "venue": "Madison Square Garden",
  "location": "New York, New York, United States",
  "videos": [],
  "sources": [],
  "created_at": { "$date": "2026-11-22T00:00:00Z" },
  "updated_at": { "$date": "2026-11-22T00:00:00Z" }
}
```

This document presumes that `muhammad-ali` and `joe-frazier` are the
slugs of Ali and Frazier, respectively. On Ali's page the displayed result would be `L UD15`;
on Frazier's page it would be `W UD15`. Exact historical details must be
verified and cited during data entry; the example is not a sourced import.

## 3. Derived values — **not** stored as authoritative copies

| Derived value | Calculation / rule |
| --- | --- |
| Boxer's age on fight day | Full years between `birth_date` and `date`. |
| Opponent's age | Same calculation using the other participant's boxer document. |
| Age text color | Exact project's RGB mapping, indexed by integer age. |
| Opponent's hyperlink | Opponent boxer exists and `published=true`. |
| Win/loss shown on a profile | Compare that profile's `slug` with `result.winner_slug`; handle draws/no-contests. |
| Calculated pre-fight record | Aggregate earlier recorded bouts for that boxer. |
| Calculated career record | Aggregate all recorded professional bouts for that boxer. |
| YouTube link/thumbnail URL | Derive from selected `videos[].youtube_id`. |
| Directory entries | Group published boxers by `weight_classes`. |

For any history marked incomplete, derived totals are provisional and
must not be represented as a verified career record. Discrepancies between
reported records and computed totals are **data-quality findings**; retain
both claims for review rather than silently changing either.

A complete-history flag should be set by deliberate verification, **not**
just because an aggregate happens to equal a reported record.

## 4. Standardization and validation

### Weight-class identifiers

Use stable machine-readable strings such as `heavyweight`,
`light-heavyweight`, `middleweight`, and `welterweight`; the application
maps these to display labels (`Heavyweight`, `Light Heavyweight`, etc.) and
table abbreviations (`HW`, `LHW`, `MW`, `WW`).

`boxers.weight_classes` records the professional divisions the boxer fought
in; `fights.weight_class` records the division for the **particular fight**.
Never infer the official division solely from one boxer's measured weight.
We will choose a complete controlled vocabulary when we implement imports.

### Initial application-level validation

- Every boxer has a nonempty `slug` and `name`; slugs are unique and
  immutable, regardless of publication status.
- `published` and `fight_history_complete` are explicit booleans, default
  `false` on creation.
- Each fight has a unique, immutable `key` assigned according to the
  fight-key convention on creation, a valid date, exactly two participants, and
  two different `boxer_slug` references that resolve to existing boxers.
- Each fight result has a recognized `outcome`; if it is a win, its
  `winner_slug` must be one of those two participants; otherwise it is absent.
- Rounds and record counts must be nonnegative where applicable; a stoppage
  round must be positive.
- Unknowns are omitted rather than fabricated; missing no-contest counts
  must not silently be interpreted as zero.
- Timestamps are populated on insert/update.
- Source/reference structure and external media links are validated before
  a profile or fight is published.

The first MongoDB-native validators can enforce basic field types and
required fields. Referential integrity, publication readiness, and the
`winner_slug`/participant relationship should be checked in Python.

## 5. Proposed indexes

| Collection | Key(s) | Index type / reason |
| --- | --- | --- |
| `boxers` | `slug` | Unique; stable boxer identity for imports, fight references, and URLs. |
| `boxers` | `weight_classes` | Multikey index to group/find boxers by class. |
| `fights` | `key` | Unique; idempotent upserts/imports. |
| `fights` | `participants.boxer_slug`, `date` | Compound multikey index for chronologically retrieving a boxer's bouts. |

MongoDB automatically indexes `_id`. Indexes should be defined and
maintained by an explicit versioned setup script when we build the app,
rather than created manually and undocumented.

## 6. Development-to-production data identity

**Environment setup:** servers have separate `mongod` instances and separate
`boxing` databases. Git deploys code, not live MongoDB data.

**Whole-database copy:** `mongodump` / `mongorestore` preserve slugs and
ObjectIds, so slug references remain valid when restoring a complete,
consistent dataset.

**Selective import:** import boxers by immutable `boxers.slug` and fights
by `fights.key`. Generate a key for new fights according to the fight-key
convention; preserve existing keys for updates, including date corrections.
Fight participant and winner slugs are portable across
servers and do not need to be translated to destination ObjectIds. Ensure
that all referenced boxer slugs resolve in the destination database before
upserting a fight. Do not use source ObjectIds as import identities; let
the destination assign `_id` values for new documents and retain existing
ones on updates.

We may store reviewed seed/import data in Git as portable JSON, using the
same boxer slugs as the database documents themselves. Imported or corrected fight
documents should not overwrite production records casually; validate,
preview, and back up before applying changes.

## 7. Decisions intentionally postponed

These are not blockers for the eight-boxer prototype:

- Full enumeration of weight classes, unusual outcomes, and championship
  title identifiers.
- Support for uncertain *partial dates* (only month/year known) while
  retaining accurate age calculations. Version 1 requires an exact bout date.
- Ring names and historical identities more complex than `name_at_fight`.
- Storing judges' scorecards and official referee details.
- Whether to track separate evidence and confidence per individual value.
- Automated imports, source reconciliation, publication checks, and
  periodic verification that YouTube links still work.
- Whether to cache appropriately licensed boxer images locally.
- The exact Python validation library and repository structure.

## 8. Summary of guiding principles

1. **One person, one boxer document; one bout, one fight document.**
2. **Unpublished opponents still get boxer identities.**
3. **Optional really means optional.** Unknown facts stay unknown.
4. **Preserve sourced historical claims and calculate derived values.**
5. **Use immutable boxer slugs for references and cross-system imports.**
6. **Track provenance and protect production data from development changes.**

## Appendix A. Exact age-color palette (display rule, **not** stored data)

The age shown is the number of **completed years** on the fight date.
Use these exact RGB values for the age text on **both** sides of a fight.
This is application behavior, not an additional `boxers` or `fights` field.

| Age | RGB | Age | RGB |
| ---: | :---: | ---: | :---: |
| 18 | `(7, 90, 9)` | 32 | `(176, 9, 69)` |
| 19 | `(56, 91, 24)` | 33 | `(165, 10, 83)` |
| 20 | `(92, 82, 21)` | 34 | `(154, 9, 94)` |
| 21 | `(134, 70, 17)` | 35 | `(142, 9, 114)` |
| 22 | `(175, 60, 14)` | 36 | `(120, 10, 127)` |
| 23 | `(206, 51, 13)` | 37 | `(103, 13, 145)` |
| 24 | `(220, 38, 13)` | 38 | `(90, 21, 161)` |
| 25 | `(235, 23, 11)` | 39 | `(77, 25, 176)` |
| 26 | `(248, 12, 12)` | 40 | `(69, 28, 187)` |
| 27 | `(232, 7, 18)` | 41 | `(63, 32, 198)` |
| 28 | `(220, 10, 32)` | 42 | `(58, 34, 209)` |
| 29 | `(207, 9, 39)` | 43 | `(51, 33, 221)` |
| 30 | `(197, 11, 48)` | 44 | `(45, 31, 229)` |
| 31 | `(184, 9, 57)` | 45 | `(11, 8, 248)` |

Below 18, use **pure green** `(0, 255, 0)`. Above 45, use **pure
blue** `(0, 0, 255)`. Unknown age has **no assigned age color**.
Do not interpolate or substitute other values for ages 18–45.
