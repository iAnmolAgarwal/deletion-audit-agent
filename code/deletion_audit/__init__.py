"""Deletion-audit pipeline package.

Subpackages present in this tree:

* ``evidence``: parses every evidence file listed in ``dataset/evidence_files.csv`` into
  :class:`~deletion_audit.evidence.model.Observation` objects.
* ``inputs``: typed loaders for ``system_activity.csv``, ``user_identities.csv`` and
  ``user_audit_log.csv``.
"""
