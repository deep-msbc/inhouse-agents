"""
ProjectSettingsUpdater — Pure Python, no LLM.
Patches INSTALLED_APPS in settings.py and urlpatterns in project urls.py.
Never touches authentication app or existing entries.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_PROTECTED_APPS = {"authentication"}


class ProjectSettingsUpdater:
    def __init__(self, project_path: str, project_name: str) -> None:
        root = Path(project_path)
        self._settings_path = root / project_name / project_name / "settings.py"
        self._urls_path = root / project_name / project_name / "urls.py"

    def add_app(self, app_name: str) -> list[str]:
        """
        Add *app_name* to INSTALLED_APPS and project urls.py.
        Returns list of error strings (empty = success).
        """
        if app_name in _PROTECTED_APPS:
            logger.debug("add_app: skipping protected app '%s'.", app_name)
            return []

        errors: list[str] = []
        if not self._settings_path.exists():
            errors.append(f"settings.py not found: {self._settings_path}")
            return errors
        if not self._urls_path.exists():
            errors.append(f"urls.py not found: {self._urls_path}")
            return errors

        errors.extend(self._patch_installed_apps(app_name))
        errors.extend(self._patch_urls(app_name))
        return errors

    def _patch_installed_apps(self, app_name: str) -> list[str]:
        content = self._settings_path.read_text(encoding="utf-8")

        if f"'{app_name}'" in content or f'"{app_name}"' in content:
            logger.debug("_patch_installed_apps: '%s' already present.", app_name)
            return []

        match = re.search(r"(INSTALLED_APPS\s*=\s*\[.*?\])", content, re.DOTALL)
        if not match:
            return [f"INSTALLED_APPS block not found in {self._settings_path}"]

        old_block = match.group(1)
        stripped = old_block.rstrip()
        if not stripped.endswith("]"):
            return [f"Cannot parse INSTALLED_APPS closing bracket in {self._settings_path}"]

        inner = stripped[:-1].rstrip()
        if inner and not inner.endswith(","):
            inner += ","
        new_block = f"{inner}\n    '{app_name}',\n]"

        self._settings_path.write_text(content.replace(old_block, new_block), encoding="utf-8")
        logger.info("_patch_installed_apps: added '%s'.", app_name)
        return []

    def _patch_urls(self, app_name: str) -> list[str]:
        content = self._urls_path.read_text(encoding="utf-8")

        if f"'{app_name}.urls'" in content or f'"{app_name}.urls"' in content:
            logger.debug("_patch_urls: '%s' already present.", app_name)
            return []

        # Ensure include is imported
        if "include" not in content:
            content = content.replace(
                "from django.urls import path",
                "from django.urls import path, include",
            )

        match = re.search(r"(urlpatterns\s*=\s*\[.*?\])", content, re.DOTALL)
        if not match:
            return [f"urlpatterns block not found in {self._urls_path}"]

        old_block = match.group(1)
        stripped = old_block.rstrip()
        if not stripped.endswith("]"):
            return [f"Cannot parse urlpatterns closing bracket in {self._urls_path}"]

        inner = stripped[:-1].rstrip()
        if inner and not inner.endswith(","):
            inner += ","
        new_entry = f"path('{app_name}/', include('{app_name}.urls'))"
        new_block = f"{inner}\n    {new_entry},\n]"

        self._urls_path.write_text(content.replace(old_block, new_block), encoding="utf-8")
        logger.info("_patch_urls: added include for '%s'.", app_name)
        return []
