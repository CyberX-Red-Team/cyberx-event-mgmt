"""The personal-data registry must cover every person-identifying column.

If this fails after adding a model or column, declare the column in
app/services/personal_data_registry.py (subject/email/name/json/other-person/
not-personal) so deletion and export both handle it.
"""
import importlib
import pkgutil
import re

import pytest

import app.models
from app.database import Base
from app.services.personal_data_registry import REGISTRY

# Column names that identify (or point at) a person.
PERSONAL_PATTERNS = [
    re.compile(p) for p in (
        r".*_email$", r"^email$", r"^user_name$", r".*_name$", r"^user_id$",
        r".*_by_user_id$", r".*_by_id$", r"^owner_id$", r"^assigned_to_.*",
        r"^sponsor_.*", r"^guardian_.*", r"^minor_.*",
    )
]

# Tables/columns matched by the patterns that are not about a person.
NOT_ABOUT_PEOPLE = {
    # Names of things, not people
    ("cloud_init_templates", "name"), ("email_templates", "name"),
    ("email_templates", "display_name"), ("email_templates", "template_name"),
    ("email_workflows", "name"), ("email_workflows", "display_name"),
    ("email_workflows", "template_name"), ("email_workflows", "from_name"),
    ("email_workflows", "from_email"), ("email_queue", "template_name"),
    ("email_events", "template_name"), ("events", "name"), ("instances", "name"),
    ("instances", "key_name"), ("instance_templates", "name"),
    ("license_products", "name"), ("license_products", "download_filename"),
    ("roles", "name"), ("service_api_keys", "name"), ("redirectors", "name"),
    ("stream_configs", "name"), ("ca_chains", "name"), ("scheduler_status", "service_name"),
    ("vpn_import_jobs", "filename"),
    ("ca_chains", "step_ca_provisioner"),
}


def _import_all_models():
    # Some models (e.g. participant_action) aren't imported by app.models.__init__.
    for mod in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{mod.name}")


def _is_personal(table, column) -> bool:
    if (table.name, column.name) in NOT_ABOUT_PEOPLE:
        return False
    if any(fk.column.table.name == "users" for fk in column.foreign_keys):
        return True
    return any(p.match(column.name) for p in PERSONAL_PATTERNS)


def test_registry_covers_every_personal_column():
    _import_all_models()
    declared: dict[str, set[str]] = {}
    for src in REGISTRY:
        declared.setdefault(src.table, set()).update(src.declared_columns())

    missing = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if table.name == "users" and column.name in {"id", "email", "first_name", "last_name"}:
                continue
            if not _is_personal(table, column):
                continue
            if column.name not in declared.get(table.name, set()):
                if table.name == "users":
                    # User's own fields are exported/deleted with the row itself.
                    continue
                missing.append(f"{table.name}.{column.name}")

    assert not missing, (
        "Person-identifying columns not in personal_data_registry: " + ", ".join(sorted(missing))
    )


def test_every_table_with_a_user_fk_is_registered():
    _import_all_models()
    registered = {src.table for src in REGISTRY}
    unregistered = sorted(
        t.name for t in Base.metadata.tables.values()
        if t.name not in registered
        and any(fk.column.table.name == "users" for c in t.columns for fk in c.foreign_keys)
    )
    assert not unregistered, f"Tables referencing users missing from the registry: {unregistered}"


@pytest.mark.parametrize("src", REGISTRY, ids=lambda s: s.key)
def test_registry_columns_exist(src):
    columns = set(src.model.__table__.c.keys())
    unknown = src.declared_columns() - columns
    assert not unknown, f"{src.key}: unknown columns {unknown}"
    assert src.on_delete in {"delete", "scrub", "keep"}


def test_cpe_name_is_kept_but_email_scrubbed():
    cpe = next(s for s in REGISTRY if s.key == "cpe_certificates")
    assert "user_email" in cpe.scrub_values()
    assert "user_name" not in cpe.scrub_values()
