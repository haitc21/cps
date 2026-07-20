# CPS and OPS Repository Migration Design

## Objective

Move the current control-plane and OpenStack provider service implementations into the new CPS and OPS repositories. Rename every technical identifier to the new service names, validate both repositories, publish their `main` branches, and retire the predecessor working directories and local development infrastructure.

## Repository migration

- Preserve each destination repository's `.git` directory and remote configuration.
- Replace all other destination content with the tracked files from its predecessor repository.
- Do not copy virtual environments, caches, build output, local secrets, Git metadata, or untracked artifacts.
- Rename package directories, modules, imports, CLI commands, environment variables, settings, tests, fixtures, schemas, documentation, plans, image tags, and service labels to CPS or OPS as appropriate.
- Do not preserve predecessor commit history.
- Regenerate dependency lockfiles and contract checksum manifests with project tooling instead of editing generated values manually.

## Local infrastructure migration

- Stop the existing development Compose project before removing any predecessor directory.
- Remove its PostgreSQL, RabbitMQ, and Valkey development volumes so no legacy database roles, database names, credentials, or persisted metadata remain.
- Configure PostgreSQL 18 with the CPS development database, role, and development-only password.
- Retain RabbitMQ 4.1 and Valkey 9.1.0 and recreate their storage from empty volumes.
- Start the Compose project from `cps/deploy/docker/docker-compose.yml` and require every service to report healthy.
- Confirm Docker Compose labels reference the CPS working directory and current configuration file.

## Validation

For each destination repository:

1. Verify no predecessor identifier remains in file content, file names, or directory names, using case-insensitive and case-sensitive scans.
2. Synchronize the locked CPython 3.12 environment.
3. Run formatting, linting, type checking, the complete test suite, contract validation, and secret scanning.
4. Run the repository's Husky pre-commit hook on the Windows host and require exit code zero.
5. Build the service image and run applicable readiness checks against the recreated local infrastructure.
6. Require `git diff --check` to pass and verify the staged tree matches the validated worktree.

## Publication and cleanup

- Create one migration commit in each destination repository on `main`.
- Push each `main` branch to its configured origin without force-pushing.
- Verify the local and remote commit IDs match.
- Only after both pushes and infrastructure verification succeed, delete the two predecessor working directories.
- Re-run filesystem and Docker metadata scans after deletion and report any residual identifier as a failure.

## Failure handling

- Do not delete predecessor directories if copying, validation, commit, push, or remote verification fails.
- Do not remove unrelated Docker resources.
- If one destination succeeds and the other fails, keep both predecessor directories until the complete migration is verified.
