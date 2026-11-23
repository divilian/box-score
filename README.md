# Box Score

**Box Score** is a historical boxing reference website that makes professional
fight records easy to explore, compare, and follow from one boxer to another.

## Functionality

### Boxer directory

The landing page lists notable professional boxers, grouped by weight class and
alphabetized within each group. Each boxer has a clickable name and portrait
thumbnail. A boxer who competed professionally in several weight classes can
appear in more than one group, while still having only one profile in the
database.

Only profiles marked as **published** will appear in this directory. (Others
are effectively placeholders for little-known boxers.)

### Boxer profiles

Each published boxer has a page containing:

- A prominent portrait in the upper-right of the profile header.
- Biographical and boxing information: names and nicknames, birth and death
  dates where known, birthplace, weight classes, height, reach, stance, etc.
- A chronological table of professional fights, showing opponent, date, each
  boxer's age, each boxer's official weigh-in weight where known, the fight's
  weight class, both pre-fight records, and the result.
- An opponent name linked to that opponent's own page (only if that profile
  is published); otherwise the name remains plain text.
- A fight result linked to a YouTube recording when a suitable recording has
  been identified. (We prefer verified full fights to highlights, and the
  shorter video when multiple verified full-fight recordings are available.)

The displayed fight result is interpreted from the perspective of the boxer
whose page is being viewed. (A fight in the database can therefore display
as a win on one page and a loss on the other.)

### Age coloring

The ages of each boxer in each row are colored using an exact, predefined
mapping for ages 18–45. Ages below 18 use pure green; ages above 45 use pure
blue. If a birthdate is not known, age is displayed as unknown rather than
guessed.

### Longer-term ideas (not in the first release)

- Sortable and filterable fight tables.
- Statistical summaries by age, opponent age, and outcome.
- Head-to-head boxer comparisons.
- Career timelines for age, weigh-in weight, and fight outcomes.
- Richer fight detail panels and multiple recording choices.

## Technology and architecture

| Layer | Planned technology |
| --- | --- |
| Application | Python + Flask |
| HTML rendering | Jinja2 templates |
| Presentation | HTML + CSS (minimal JavaScript if useful) |
| Database | MongoDB Community Edition |
| Production app server | Gunicorn |
| Production web server | Nginx with HTTPS |
| Source control | Git / GitHub |

The MongoDB database is named **`boxing`** and has two collections:

- **`boxers`** — one document per boxer, including minimal records for
  opponents who do not have published profile pages.
- **`fights`** — one document per professional bout, referencing exactly two
  boxers. The same fight is never duplicated for its two participants.

The database is the source of truth for the website. We do not maintain
separate generated Markdown files as the live source for each boxer page.

See **[docs/schema.md](docs/schema.md)** for the proposed data model,
examples, constraints, and indexing decisions.

### Security and configuration principles

- No MongoDB server should expose port 27017 to the public Internet.
- The production database should listen on loopback and be accessed locally
  by the production application.
- Use SSH tunnels for occasional remote database administration.
- Keep configuration and secrets out of Git (environment variables or a
  protected environment-specific configuration file).
- Back up production data regularly, including an off-host copy, and test
  restores.
- Do not assume a development database can safely overwrite production after
  production data begins to evolve independently.

## Data quality and provenance

Historical boxing records can be incomplete or disputed. Box Score will:

- Preserve uncertainty: optional fields stay absent if not reliably known.
- Store independently sourced pre-fight records, even when a calculation from
  the local database gives a different result; discrepancies should be
  **flagged and investigated**, not silently overwritten.
- Distinguish externally reported career records from totals calculated from
  the fight documents.
- Track whether an individual's professional fight history has been verified
  as complete.
- Retain source references for biographical facts and fight details.
- Preserve attribution and license information for fighter portraits.
- Link to YouTube recordings rather than treating those videos as our files.

A boxer's calculated record is only comprehensive if that boxer's fight
history in the database is complete.

## License

Box Score's application source code is licensed under the MIT License. Boxing
records, photographs, videos, and other third-party content are not covered by
this license and may be subject to separate terms.
