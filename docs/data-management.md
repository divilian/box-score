# Box Score Data Management

## Source of Truth

Git is the authoritative source for Box Score's software, configuration, schema definitions, and documentation.

MongoDB is the authoritative source for Box Score's historical boxing data.

JSON files are a means of transporting and importing data, not a parallel representation of the database that must be kept synchronized.

## Data Imports

JSON files may be used to deliver newly researched boxer profiles, fight histories, and other historical information.

Import utilities should:

- Validate incoming data.
- Generate stable identifiers where necessary.
- Preserve existing creation timestamps.
- Update modification timestamps when data changes.
- Prevent duplicate documents.
- Avoid silently overwriting existing information.

Importing the same file multiple times should be idempotent.

## Data Maintenance

Corrections and additions may be made directly to MongoDB, either through command-line utilities, mongosh, or a future administrative interface.

Such changes do not require corresponding changes to JSON files or commits to Git.

## Test Data

A small, self-contained prototype dataset shall be maintained in the Git repository for development, testing, and demonstration purposes.

This dataset is not intended to remain synchronized with the production database.

## Environments

Box Score distinguishes between two deployment environments:

- **Development:** A local database used for application development, experimentation, and testing.
- **Production:** The authoritative database serving the deployed application.

Production data may periodically be copied to the development environment. Development data should never automatically overwrite production data.

Until production is deployed, the designated development database serves as the initial authoritative database.

Environment-specific connection details are supplied through environment variables rather than hard-coded into application code or committed to the repository.

## Backups and Recovery

Database backups shall use MongoDB's native mongodump and mongorestore utilities, preserving BSON data types, collection metadata, validators, and indexes.

Production backups should be automated and periodically tested for recoverability.

Database backups and temporary import files shall not be committed to Git.

## Schema Evolution

Schema changes shall be documented in docs/schema.md and reflected in the database initialization script and any necessary migration utilities.

MongoDB validators enforce the requirements and types of recognized fields but intentionally permit additional fields. This allows historical data to evolve organically without requiring a formal schema revision for every new attribute.
