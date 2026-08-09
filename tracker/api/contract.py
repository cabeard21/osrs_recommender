"""Loading and validating against ``contracts/sync_payload.schema.json`` (§12.1).

**The JSON Schema file is the only declaration of the payload shape.** It is not
re-expressed as a Pydantic model here, and must not be: §12.1 gives the seam a single
owner because the Java plugin and the Python app both read it, and a second Python-side
declaration would be a third party to that agreement — one that drifts silently, since
nothing fails when the two disagree about a field the tests happen not to exercise. That
is why ``jsonschema`` is a runtime dependency rather than a dev one.

The consequence is that the request body arrives as a plain ``dict``, not as a typed
model. Step 8b's merge layer is where those keys become domain objects; this module's job
ends at "the payload conforms".

**On ``format: date-time``.** JSON Schema treats ``format`` as an annotation by default,
asserted only when a format checker is installed, and ``jsonschema``'s date-time checker
needs an optional third-party package. Enabling it would mean the contract enforced
different things depending on which extras happened to be installed — so the schema
carries an explicit ``pattern`` on every timestamp instead, and this module deliberately
builds the validator *without* a format checker. The pattern is the enforcement.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

#: ``tracker/api/contract.py`` -> ``tracker/api`` -> ``tracker`` -> repo root.
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "sync_payload.schema.json"


def load_sync_payload_schema() -> dict[str, Any]:
    """The schema as a plain dict, freshly parsed.

    Not cached, unlike the validator: callers that inspect the schema (the contract tests
    read ``x-status``) get a copy they cannot accidentally share with the validator's.
    """
    schema: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return schema


@lru_cache(maxsize=1)
def sync_payload_validator() -> Draft202012Validator:
    """A validator over the contract, built once per process.

    ``check_schema`` runs here rather than only in a test, so a malformed contract fails at
    the first request with a message about the *schema* instead of producing a confusing
    per-payload error.
    """
    schema = load_sync_payload_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def describe_validation_error(error: ValidationError) -> str:
    """A one-line, path-anchored summary, for a 422 body and for ``SyncEvent.reason``.

    ``jsonschema``'s own ``str(error)`` is a multi-line report quoting the whole failing
    instance, which for a full bank scan runs to thousands of lines — unusable both as an
    HTTP response and as an audit column. The path is what a plugin author actually needs.
    """
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_sync_payload(payload: object) -> str | None:
    """``None`` when ``payload`` conforms, else a one-line description of the first failure.

    "First" is made deterministic by sorting on the instance path rather than taking
    whichever error the validator yields first: a payload with several problems must
    produce the same message on every run, or one broken plugin build reports a different
    error each sync.
    """
    validator = sync_payload_validator()
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if not errors:
        return None
    return describe_validation_error(errors[0])
