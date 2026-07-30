# coding: utf-8

"""
Configuration input/output management module for workspaces.

This module provides the :class:`ConfigIO` class, the data access layer
of the QWorkspace Switcher plugin. It relies on
:class:`~perspective_manager.core.configuration.Configuration` as the
single source of truth in memory (``self._cfg``), and synchronizes
changes to ``user.psp.json``.

**Configuration source architecture:**

.. code-block:: text

    CONFIG_DEFAULT              (lowest priority)
        ↓
    plugin_a/plugin_a.psp.json  (workspaces declared by plugin_a)
        ↓
    plugin_b/plugin_b.psp.json  (workspaces declared by plugin_b)
        ↓
    perspectives/user.psp.json  (user workspaces — highest priority)
        ↓
    self._cfg                   (merged dictionary in memory)

**How it works:**

- At startup, :meth:`_build_cfg` scans all ``*.psp.json`` files
  from installed QGIS plugins and merges them with ``user.psp.json``.
- During the session, all operations (read, write, delete)
  go exclusively through ``self._cfg`` — no file reading.
- Each modification updates ``self._cfg`` then writes ``user.psp.json``.
- A :class:`QFileSystemWatcher` detects external file modifications
  and automatically rebuilds ``self._cfg``.

:author: Adnan Benaboud — CNR
"""

import os
import json
import glob

from qgis.PyQt.QtCore import QObject, pyqtSignal, QFileSystemWatcher

from .configuration import Configuration


#: Default configuration — empty workspace list.
CONFIG_DEFAULT = {"perspectives": []}


class ConfigIO(QObject):
    """
    Input/output manager for plugin workspaces.

    Provides a unified API to read, create, modify and delete
    workspaces. Relies on :class:`Configuration` as the single
    source of truth in memory.

    **Managed files:**

    - ``perspectives/user.psp.json`` — workspaces created by the user.
    - ``<plugin>/<plugin>.psp.json`` — workspaces declared by plugins
      (read-only, loaded at startup).

    **Signals:**

    - :attr:`configChanged` — emitted when ``user.psp.json`` is modified
      from outside (e.g. text editor).

    :example:

    .. code-block:: python

        config_io = ConfigIO()
        data      = config_io.load("Field survey")
        config_io.save("Field survey", data)
    """

    configChanged = pyqtSignal()
    """Signal emitted when ``user.psp.json`` is modified from outside."""

    CONFIG_FILE = "user.psp.json"
    """Name of the user configuration file."""

    def __init__(self):
        """
        Initialize the configuration manager.

        - Creates the ``perspectives/`` directory if necessary.
        - Builds ``self._cfg`` from all available sources.
        - Starts the :class:`QFileSystemWatcher` on ``user.psp.json``.
        """
        super().__init__()

        self.base_dir    = self._get_base_dir()
        self.config_path = os.path.join(self.base_dir, self.CONFIG_FILE)
        self._writing    = False

        os.makedirs(self.base_dir, exist_ok=True)

        # Single source of truth
        self._cfg = self._build_cfg()

        # Watch for external modifications
        self._watcher = QFileSystemWatcher()
        self._watcher.addPath(self.config_path)
        self._watcher.fileChanged.connect(self._on_file_changed)

    # ─────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────

    def _get_base_dir(self) -> str:
        """
        Return the path to the workspace storage directory.

        :return: Absolute path to ``<plugin_dir>/perspectives/``.
        :rtype: str
        """
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        return os.path.join(plugin_dir, "perspectives")

    def _build_cfg(self) -> Configuration:
        """
        Build the single source of truth from all sources.

        Scans all ``*.psp.json`` files from installed QGIS plugins,
        merges them with ``user.psp.json`` via :class:`Configuration`,
        then fixes the perspective list merge via
        :meth:`_merge_perspectives`.

        Called at startup and on external reload.

        :return: Merged :class:`Configuration` instance.
        :rtype: Configuration
        """
        lst_cfg     = [CONFIG_DEFAULT]
        plugins_dir = os.path.dirname(os.path.dirname(self.base_dir))

        psp_files = sorted(glob.glob(
            os.path.join(plugins_dir, "*", "*.psp.json")
        ))

        for fic in psp_files:
            if os.path.normpath(fic) == os.path.normpath(self.config_path):
                continue
            lst_cfg.append(fic)

        cfg = Configuration(
            lst_cfg=lst_cfg,
            fic_sav=self.config_path
        )

        merged = self._merge_perspectives(lst_cfg + [self.config_path])
        cfg.cfg["perspectives"] = merged

        return cfg

    def _merge_perspectives(self, lst_cfg: list) -> list:
        """
        Merge workspaces from all sources by priority order.

        User workspaces (``user.psp.json``) take priority over
        plugin workspaces. In case of identical names, the user
        version overrides the plugin version.

        Workspaces listed in ``deleted_perspectives`` of
        ``user.psp.json`` are excluded from the result.

        **Order in the returned list:**

        1. User workspaces (``user.psp.json``) first.
        2. Non-overridden plugin workspaces next.

        :param lst_cfg: List of sources — each element is a
            :class:`dict` or a path to a JSON file.
        :type lst_cfg: list
        :return: Merged and ordered list of workspaces.
        :rtype: list

        :example:

        .. code-block:: text

            georelai.psp.json → [Modeling, Visualization]
            user.psp.json     → [QGIS, Visualization (modified)]

            Result → [QGIS, Modeling, Visualization (user)]
        """
        if not lst_cfg:
            return []

        # Read blacklist from user.psp.json
        deleted = []
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
                deleted = user_data.get("deleted_perspectives", [])
        except Exception:
            pass

        user_perspectives   = {}
        plugin_perspectives = {}

        for source in lst_cfg:
            if source is None:
                continue

            is_user = (
                isinstance(source, str) and
                os.path.normpath(source) == os.path.normpath(
                    self.config_path
                )
            )

            if isinstance(source, dict):
                perspectives = source.get("perspectives", [])
            elif isinstance(source, str):
                path = os.path.normpath(source)
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    perspectives = data.get("perspectives", [])
                except Exception as e:
                    print(f"[ConfigIO] Read error {path}: {e}")
                    perspectives = []
            else:
                continue

            for p in perspectives:
                name = p.get("name")
                if not name:
                    continue
                if name in deleted:  # ← respect blacklist
                    continue
                if is_user:
                    user_perspectives[name]   = p
                else:
                    plugin_perspectives[name] = p

        # Merge: user overrides plugins on name conflict
        result       = dict(plugin_perspectives)
        result.update(user_perspectives)
        user_names   = list(user_perspectives.keys())
        plugin_names = [
            n for n in plugin_perspectives
            if n not in user_perspectives
        ]

        return [result[n] for n in user_names + plugin_names]

    def _on_file_changed(self, path: str):
        """
        Called by :attr:`_watcher` when ``user.psp.json`` is modified.

        Ignores modifications coming from the plugin itself
        (``_writing`` flag). Rebuilds ``self._cfg`` from all sources
        and emits :attr:`configChanged`.

        :param path: Path of the modified file.
        :type path: str
        """
        if self._writing:
            # Internal modification → only re-add to watcher
            if os.path.exists(path) and path not in self._watcher.files():
                self._watcher.addPath(path)
            return  # ← do NOT rebuild self._cfg

        # External modification → rebuild
        if os.path.exists(path) and path not in self._watcher.files():
            self._watcher.addPath(path)

        self._cfg = self._build_cfg()
        self.configChanged.emit()

    # ─────────────────────────────────────────────
    # PUBLIC API — everything goes through self._cfg
    # ─────────────────────────────────────────────

    def list_all(self) -> list:
        """
        Return the names of all workspaces from ``self._cfg``.

        Includes both user and plugin workspaces.

        :return: List of workspace names in display order
            (user first, plugins next).
        :rtype: list[str]

        :example:

        .. code-block:: python

            names = config_io.list_all()
            # → ['QGIS', 'Field survey', 'Modeling', 'qats']
        """
        return [
            p["name"]
            for p in self._cfg.get("perspectives", [])
        ]

    def list_all_merged(self) -> list:
        """
        Alias for :meth:`list_all`.

        Kept for compatibility with existing calls.

        :return: List of all workspace names.
        :rtype: list[str]
        """
        return self.list_all()

    def load(self, name: str) -> dict:
        """
        Load a workspace by name from ``self._cfg``.

        No file reading — in-memory operation only.

        :param name: Name of the workspace to load.
        :type name: str
        :return: Complete workspace dictionary,
            or empty dictionary if not found.
        :rtype: dict

        :example:

        .. code-block:: python

            data     = config_io.load("Field survey")
            show_menu = data.get("show_menu_bar", True)
        """
        for p in self._cfg.get("perspectives", []):
            if p["name"] == name:
                return p
        return {}

    def save(self, name: str, data: dict):
        """
        Save a workspace to ``self._cfg`` and ``user.psp.json``.

        If the workspace already exists, it is updated. Otherwise it
        is added (the ``QGIS`` workspace is always inserted first).

        :param name: Name of the workspace.
        :type name: str
        :param data: Complete workspace dictionary.
        :type data: dict
        """
        self._writing = True
        try:
            data["name"]  = name
            perspectives  = self._cfg.get("perspectives", [])

            for i, p in enumerate(perspectives):
                if p["name"] == name:
                    perspectives[i] = data
                    self._cfg["perspectives"] = perspectives
                    self._cfg.sgl_unsaved.emit()
                    self._write_user_from_cfg()
                    return

            if name == "QGIS":
                perspectives.insert(0, data)
            else:
                perspectives.append(data)

            self._cfg["perspectives"] = perspectives
            self._cfg.sgl_unsaved.emit()
            self._write_user_from_cfg()

        except Exception as e:
            print(f"[ConfigIO] Save error: {e}")

        finally:
            self._writing = False

    def delete(self, name: str):
        """
        Delete a workspace from ``self._cfg`` and ``user.psp.json``.

        If the workspace comes from a plugin ``*.psp.json`` file,
        it is added to ``deleted_perspectives`` in ``user.psp.json``
        to be filtered on next plugin reload.

        .. note::
            Deletion is immediate in ``self._cfg`` — the workspace
            disappears from the UI and toolbar without reloading.
            It will be permanently absent on next startup thanks
            to ``deleted_perspectives``.

        :param name: Name of the workspace to delete.
        :type name: str
        """
        self._writing = True
        try:
            # Remove from self._cfg — immediate effect
            perspectives = [
                p for p in self._cfg.get("perspectives", [])
                if p["name"] != name
            ]
            self._cfg["perspectives"] = perspectives
            self._cfg.sgl_unsaved.emit()

            # Persist in user.psp.json
            user_data = self._read_user()

            user_data["perspectives"] = [
                p for p in user_data.get("perspectives", [])
                if p["name"] != name
            ]

            # If plugin workspace → add to blacklist
            if name in self.get_plugin_perspectives():
                deleted = user_data.get("deleted_perspectives", [])
                if name not in deleted:
                    deleted.append(name)
                user_data["deleted_perspectives"] = deleted

            self._write_user(user_data)

        finally:
            self._writing = False

    def rename(self, old_name: str, new_name: str):
        """
        Rename a workspace in ``self._cfg`` and ``user.psp.json``.

        :param old_name: Current name of the workspace.
        :type old_name: str
        :param new_name: New name of the workspace.
        :type new_name: str
        """
        self._writing = True
        try:
            # Rename in self._cfg
            perspectives = self._cfg.get("perspectives", [])
            for p in perspectives:
                if p["name"] == old_name:
                    p["name"] = new_name
                    break
            self._cfg["perspectives"] = perspectives
            self._cfg.sgl_unsaved.emit()

            # Rename in user.psp.json
            user_data  = self._read_user()
            user_persp = user_data.get("perspectives", [])
            for p in user_persp:
                if p["name"] == old_name:
                    p["name"] = new_name
                    break
            user_data["perspectives"] = user_persp
            self._write_user(user_data)

        finally:
            self._writing = False

    def create_perspective(self, name: str) -> bool:
        """
        Create a new empty workspace.

        :param name: Name of the new workspace.
        :type name: str
        :return: ``True`` if created successfully,
            ``False`` if the name already exists.
        :rtype: bool

        :example:

        .. code-block:: python

            if config_io.create_perspective("My workflow"):
                print("Created!")
        """
        if name in self.list_all():
            return False

        empty = {
            "name":           name,
            "icon":           "",
            "button_style":   "text",
            "show_menu_bar":  True,
            "dropdown_menus": [],
            "plugins":        {}
        }
        self.save(name, empty)
        return True

    def validate(self, data: dict) -> bool:
        """
        Validate the minimal structure of a workspace dictionary.

        :param data: Dictionary to validate.
        :type data: dict
        :return: ``True`` if the dictionary contains the required keys.
        :rtype: bool
        """
        return "name" in data and "plugins" in data

    def get_plugin_perspectives(self) -> dict:
        """
        Return workspaces declared by installed plugins.

        Scans all ``*.psp.json`` files from QGIS plugins
        (excluding ``user.psp.json``) and returns a dictionary
        ``{workspace_name: plugin_name}``.

        :return: Dictionary mapping each workspace to its plugin.
        :rtype: dict[str, str]

        :example:

        .. code-block:: python

            plugin_persp = config_io.get_plugin_perspectives()
            # → {"Modeling": "georelai", "Meshing": "meshwidgets"}
        """
        result      = {}
        plugins_dir = os.path.dirname(os.path.dirname(self.base_dir))
        psp_files   = glob.glob(
            os.path.join(plugins_dir, "*", "*.psp.json")
        )

        for fic in psp_files:
            if os.path.normpath(fic) == os.path.normpath(self.config_path):
                continue
            plugin_name = os.path.basename(os.path.dirname(fic))
            try:
                with open(fic, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for p in data.get("perspectives", []):
                    name = p.get("name")
                    if name:
                        result[name] = plugin_name
            except Exception:
                pass

        return result

    # ─────────────────────────────────────────────
    # PRIVATE METHODS
    # ─────────────────────────────────────────────

    def _read_user(self) -> dict:
        """
        Read ``user.psp.json`` directly from disk.

        :return: Content of ``user.psp.json``, or ``{"perspectives": []}``
            if the file is missing or corrupted.
        :rtype: dict
        """
        if not os.path.exists(self.config_path):
            return {"perspectives": []}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f) or {"perspectives": []}
        except Exception as e:
            print(f"[ConfigIO] Read error: {e}")
            return {"perspectives": []}

    def _write_user(self, data: dict):
        """
        Write directly to ``user.psp.json`` on disk.

        Emits :attr:`Configuration.sgl_saved` after writing.

        :param data: Dictionary to save.
        :type data: dict
        """
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._cfg.sgl_saved.emit()
        except Exception as e:
            print(f"[ConfigIO] Write error: {e}")

    def _write_user_from_cfg(self):
        """
        Write ``user.psp.json`` from ``self._cfg``.

        Only saves workspaces belonging to the user.
        Plugin workspaces are included only if they have been
        modified by the user (overrides).

        Preserves ``deleted_perspectives`` from the existing file.

        **Logic:**

        - Non-plugin workspace → always written.
        - Unmodified plugin workspace → ignored.
        - Modified plugin workspace → written as override.
        - ``deleted_perspectives`` → always preserved.
        """
        plugin_perspectives  = self.get_plugin_perspectives()
        original_plugin_data = {}

        # Load original plugin versions to detect overrides
        plugins_dir = os.path.dirname(os.path.dirname(self.base_dir))
        for name, plugin_name in plugin_perspectives.items():
            psp_files = glob.glob(
                os.path.join(plugins_dir, plugin_name, "*.psp.json")
            )
            if not psp_files:
                continue
            try:
                with open(psp_files[0], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for p in data.get("perspectives", []):
                    if p.get("name") == name:
                        original_plugin_data[name] = p
                        break
            except Exception:
                pass

        # Build the list to write
        user_perspectives = []
        for p in self._cfg.get("perspectives", []):
            name = p.get("name")
            if name not in plugin_perspectives:
                # User workspace → always write
                user_perspectives.append(p)
            else:
                # Plugin workspace → write only if modified (override)
                original = original_plugin_data.get(name)
                if original and p != original:
                    user_perspectives.append(p)

        # Build final dictionary
        user_data = {"perspectives": user_perspectives}

        # Preserve deleted_perspectives from existing file
        existing_user = self._read_user()
        if "deleted_perspectives" in existing_user:
            user_data["deleted_perspectives"] = existing_user[
                "deleted_perspectives"
            ]

        self._write_user(user_data)