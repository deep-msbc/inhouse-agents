"""
ScaffoldValidator — verifies djcli created the expected file tree.

Runs immediately after CLIInvoker succeeds. Checks that every Django app
directory contains the 5 required files before code generation begins.
If any file is missing, the pipeline fails fast rather than attempting
LLM generation into a broken scaffold.

djcli directory layout
----------------------
  output_path/
  └── project_name/               ← project root
      ├── manage.py
      ├── project_name/           ← Django settings package
      │   └── settings.py
      ├── app1/
      │   ├── models.py
      │   ├── serializers.py
      │   ├── views.py
      │   ├── urls.py
      │   └── __init__.py
      └── app2/ ...

Expected files per app (relative to project_root = output_path/project_name):
  {app_name}/models.py
  {app_name}/serializers.py
  {app_name}/views.py
  {app_name}/urls.py
  {app_name}/__init__.py
"""

from __future__ import annotations

import logging
import os

from src.msbc.models.schemas.backend_pipeline import ValidationResult

logger = logging.getLogger(__name__)

# Files that djcli must create inside every app directory.
_REQUIRED_APP_FILES: tuple[str, ...] = (
    "models.py",
    "serializers.py",
    "views.py",
    "urls.py",
    "__init__.py",
)


class ScaffoldValidator:
    """
    Validates the djcli-generated project scaffold.

    Usage::

        validator = ScaffoldValidator()
        result = validator.validate(project_path, project_name, app_names)
        if not result.success:
            # halt pipeline — missing_files tells you exactly what's absent
    """

    def validate(
        self,
        project_path: str,
        project_name: str,
        app_names: list[str],
        generation_mode: str = "startproject",
    ) -> ValidationResult:
        """
        Check that every app in *app_names* has all required files.

        Parameters
        ----------
        project_path : str
            For startproject/startapp: the project root (output_path/project_name).
            For startservices: output_path (services are top-level dirs inside it).
        project_name : str
            The project name (used to locate the settings package).
        app_names : list[str]
            Sanitised app names to check.
        generation_mode : str
            "startproject" | "startapp" | "startservices"

        Returns
        -------
        ValidationResult
            success=True only if every expected file exists on disk.
        """
        missing: list[str] = []
        errors: list[str] = []

        if generation_mode == "startservices":
            # project_path == output_path
            # djcli startservices creates: output_path/svc_<app>/app/<files>
            for app in app_names:
                service_dir = os.path.join(project_path, f"svc_{app}")
                if not os.path.isdir(service_dir):
                    for fname in _REQUIRED_APP_FILES:
                        missing.append(f"svc_{app}/app/{fname}")
                    logger.warning("ScaffoldValidator: service dir missing — %s", service_dir)
                    continue
                app_dir = os.path.join(service_dir, "app")
                if not os.path.isdir(app_dir):
                    for fname in _REQUIRED_APP_FILES:
                        missing.append(f"svc_{app}/app/{fname}")
                    logger.warning("ScaffoldValidator: app dir missing — %s", app_dir)
                    continue
                for fname in _REQUIRED_APP_FILES:
                    fpath = os.path.join(app_dir, fname)
                    if not os.path.isfile(fpath):
                        missing.append(f"svc_{app}/app/{fname}")
                        logger.warning("ScaffoldValidator: missing file — svc_%s/app/%s", app, fname)
        else:
            # startproject / startapp
            # project_path IS the project root (output_path/project_name)
            if not os.path.isdir(project_path):
                errors.append(
                    f"project root does not exist or is not a directory: {project_path!r}"
                )
                return ValidationResult(
                    success=False,
                    project_path=project_path,
                    missing_files=[],
                    errors=errors,
                )

            # settings.py at project_path/project_name/settings.py
            settings_path = os.path.join(project_path, project_name, "settings.py")
            if not os.path.isfile(settings_path):
                missing.append(f"{project_name}/settings.py")
                logger.warning("ScaffoldValidator: settings.py missing — %s", settings_path)

            for app in app_names:
                app_dir = os.path.join(project_path, app)
                if not os.path.isdir(app_dir):
                    for fname in _REQUIRED_APP_FILES:
                        missing.append(f"{app}/{fname}")
                    logger.warning("ScaffoldValidator: app directory missing — %s", app_dir)
                    continue
                for fname in _REQUIRED_APP_FILES:
                    fpath = os.path.join(app_dir, fname)
                    if not os.path.isfile(fpath):
                        missing.append(f"{app}/{fname}")
                        logger.warning("ScaffoldValidator: missing file — %s/%s", app, fname)

        success = len(missing) == 0 and len(errors) == 0

        if success:
            logger.info(
                "ScaffoldValidator: all files present for %d app(s) (mode=%r)",
                len(app_names),
                generation_mode,
            )
        else:
            logger.error(
                "ScaffoldValidator: %d missing file(s), %d error(s) (mode=%r)",
                len(missing),
                len(errors),
                generation_mode,
            )

        return ValidationResult(
            success=success,
            project_path=project_path,
            missing_files=missing,
            errors=errors,
        )