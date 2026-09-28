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
import copy

from qgis.PyQt.QtCore import QObject, pyqtSignal, QFileSystemWatcher

from .configuration import Configuration


#: Default configuration
CONFIG_DEFAULT = {
    "ico_left": True,       # QWS configuration button is on the left side of the toolbar
    "ico_spacer": True,     # QWS configuration button is separated from the perpective buttons
    "ico_cfg": "icon.png",  # QWS configuration button icon
    "dic_psp": {}           # Dict of workspaces (= perspectives) {name: dic_properties}
}
PSP_DEFAULT = {
    "is_visible": True,     # Allows to mask some perspectives (rather than maintaining a ``deleted_perspectives`` list)
    "order": 999,           # New perspective comes last; TODO edit perspective order
    "icon": "",             # Icon associated with the perspective
    "button_style": "text", # Combination of text and icon
    "show_menu_bar": True,  # Shows the main QGIS menu bar for this perspective
    "dropdown_menus": [],   # TODO: for Panels/Toolbars/Menus: use dict rather than list, to fully benefit of class Configuration
    "plugins": {}
}


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

        Merges various workspaces (perspectives) configurations: from
        ``*.psp.json`` files for installed QGIS plugins, and from ``user.psp.json``.
        The hierarchical merge est is done by :class:`Configuration`, and the mixing can
        be intimate if dict structures (better than list structures) are used for
        perspective configurations.

        Called at startup and on external reload.

        :return: Merged :class:`Configuration` instance.
        :rtype: Configuration
        """
        lst_cfg = [CONFIG_DEFAULT]              # Least dominant config

        plugins_dir = os.path.dirname(os.path.dirname(self.base_dir))
        psp_files = sorted(glob.glob(
            os.path.join(plugins_dir, "*", "*.psp.json")
        ))
        for fic in psp_files:
            if os.path.normpath(fic) == os.path.normpath(self.config_path):
                continue
            lst_cfg.append(fic)                 # Increasingly dominant configs

        lst_cfg.append(self.config_path)        # Most dominant config

        # Configuration object merges the psp configs
        cfg = Configuration(
            lst_cfg=lst_cfg,                    # List of config sources, from least dominant to most dominant
            fic_sav=self.config_path            # User file to save config to
        )

        return cfg

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
        Return the names of all workspaces from ``self._cfg``, except not is_visible.

        :return: List of workspace names in display order.
        :rtype: list[str]

        :example:

        .. code-block:: python

            names = config_io.list_all()
            # → ['QGIS', 'Field survey', 'Modeling', 'qats']
        """
        lst_psp = [k for k, v in self._cfg["dic_psp"].items()
            if v.get("is_visible") != False]
        lst_psp = sorted(lst_psp, key=lambda k: self._cfg["dic_psp"][k].get("order", 999))
        return lst_psp

    def load(self, name: str) -> dict:
        """
        Load a workspace by name from ``self._cfg``.

        No file reading — in-memory operation only. Returns a deep
        copy, never the live dictionary stored in ``self._cfg`` —
        a caller mutating the result (e.g. to rename it before
        saving under a different name, as duplication does) must
        not silently corrupt the original in-memory workspace.

        :param name: Name of the workspace to load.
        :type name: str
        :return: Complete workspace dictionary (independent copy),
            or empty dictionary if not found.
        :rtype: dict

        :example:

        .. code-block:: python

            data     = config_io.load("Field survey")
            show_menu = data.get("show_menu_bar", True)
        """
        if name not in self._cfg["dic_psp"]:
            self.create_perspective(name)
        return copy.deepcopy(self._cfg["dic_psp"][name])

    def save(self, name: str, data: dict):
        """
        Save a workspace to ``self._cfg`` and ``user.psp.json``.

        If the workspace already exists, it is updated. Otherwise it
        is added (the ``QGIS`` workspace is always inserted first).

        CHANGE 2 / CHANGE 4 — no special handling was added here for
        the ``"window_state"`` field or per-dock ``"tab_order"``
        (both captured by
        :meth:`~perspective_manager.applicators.state_capture.
        StateCapture.capture`): ``save``/``load`` already persist
        and return whatever keys ``data`` (and each dock dict inside
        it) contains, generically — same as ``show_menu_bar`` or
        ``icon`` — so adding a dedicated branch here would just
        duplicate that existing behavior.

        :param name: Name of the workspace.
        :type name: str
        :param data: Complete workspace dictionary.
        :type data: dict
        """
        self._writing = True
        try:
            self._cfg["dic_psp"][name] = data
            self._cfg.save(diff=True)
        except Exception as e:
            print(f"[ConfigIO] Save error: {e}")
        finally:
            self._writing = False

    def delete(self, name: str):
        """
        Hide a workspace from ``self._cfg`` and ``user.psp.json`` (simulate a deletion
        without actually erasing the perspective: no more need for ``deleted_perspectives``).

        .. note::
            Deletion is immediate in ``self._cfg`` — the workspace
            disappears from the UI and toolbar without reloading.

        :param name: Name of the workspace to delete.
        :type name: str
        """
        self._writing = True
        try:
            self._cfg["dic_psp"][name]["is_visible"] = False
            self._cfg.save(diff=True)
        finally:
            self._writing = False

    def rename(self, old_name: str, new_name: str):
        """
        Rename a workspace in ``self._cfg`` and ``user.psp.json``: add the new one by
        deep copy, and mask the old one (mask it even if declared by another app).

        :param old_name: Current name of the workspace.
        :type old_name: str
        :param new_name: New name of the workspace.
        :type new_name: str
        """
        self._writing = True
        try:
            psp_cfg = self.load_psp(old_name)   # Deep copy
            self._cfg["dic_psp"][new_name] = psp_cfg
            self._cfg["dic_psp"][new_name]["is_visible"] = True
            self.delete(old_name)
            self._cfg.save(diff=True)
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

        psp_dft = PSP_DEFAULT
        psp_dft["order"] = len(self._cfg["dic_psp"])
        self.save(name, psp_dft)
        return True
