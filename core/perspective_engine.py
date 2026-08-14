# coding: utf-8

"""
Main engine module of the QWorkspace Switcher plugin.

This module provides the :class:`PerspectiveEngine` class, the orchestrator
of the plugin. It coordinates
:class:`~perspective_manager.core.plugin_discovery.PluginDiscovery`,
:class:`~perspective_manager.core.config_io.ConfigIO` and the applicators
to apply workspaces on the QGIS interface.

**Workspace application flow:**

.. code-block:: text

    apply("Field survey")
        │
        ├── Pass 0 — restoreState(window_state), if present
        │       → geometry baseline only (splitters, floating
        │         geometry, tab order) — never overrides what
        │         the passes below decide
        │
        ├── Pass 1 — _hide_all()
        │       → hides all docks and toolbars
        │
        ├── Pass 2 — DockApplicator.apply()
        │       → positions and shows docks
        │
        ├── Pass 3 — ToolbarApplicator.apply_all()
        │       → positions and shows toolbars
        │
        └── Pass 4 — menuBar().setVisible()
                → shows/hides the QGIS menu bar

**Excluded toolbars** (never force-hidden by ``_hide_all``):

- ``QWorkspaceSwitcherToolbar`` — the plugin's own toolbar. Its
  position (area/line/order) still comes from its own workspace
  configuration entry, applied like any other toolbar in
  ``ToolbarApplicator.apply_all()`` — only its visibility is
  protected here, so it can never be hidden out of reach.
- ``QToolBar`` — widgets without a valid name.

**Linked toolbars** (automatically follow their dock):

- ``mBrowserToolbar`` → dock ``Browser``
- ``mGpsToolBar`` → dock ``GPSInformation``
- ``mBookmarkToolbar`` → dock ``BookmarksDockWidget``
- ``processingToolbar`` → dock ``ProcessingToolbox``

:author: Adnan Benaboud — CNR
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal, Qt, QByteArray
from qgis.PyQt.QtWidgets import QDockWidget, QToolBar
from qgis.utils import iface

from .plugin_discovery import PluginDiscovery, is_valid
from .config_io import ConfigIO
from ..applicators.dock_applicator import DockApplicator
from ..applicators.toolbar_applicator import ToolbarApplicator
from ..applicators.state_capture import StateCapture


#: Toolbars linked to a dock — visibility follows the dock via Qt signal.
LINKED_TOOLBARS = {
    "mBrowserToolbar",
    "mGpsToolBar",
    "mBookmarkToolbar",
    "processingToolbar",
}

#: Toolbars never force-hidden by :meth:`PerspectiveEngine._hide_all`.
#: Positioning is a separate concern, handled by
#: :data:`applicators.toolbar_applicator.EXCLUDED_TOOLBARS`.
EXCLUDED_TOOLBARS = {
    "QWorkspaceSwitcherToolbar",
    "QToolBar",
}


class PerspectiveEngine(QObject):
    """
    Orchestrator of the QWorkspace Switcher plugin.

    Coordinates plugin discovery, configuration management
    and workspace application on the QGIS interface.

    **Responsibilities:**

    - Scan installed QGIS plugins via :class:`PluginDiscovery`.
    - Read and write workspaces via :class:`ConfigIO`.
    - Apply workspaces (docks, toolbars, menu bar).
    - Maintain automatic dock ↔ toolbar links.
    - Emit :attr:`perspectiveChanged` on changes.

    :example:

    .. code-block:: python

        engine = PerspectiveEngine()
        engine.initialize()
        engine.apply("Field survey")
    """

    perspectiveChanged = pyqtSignal(str)
    """
    Signal emitted after a workspace is applied.

    Transmits the name of the applied workspace, or ``"__reload__"``
    on external configuration reload.
    """

    DEFAULT_PERSPECTIVE_NAME = "QGIS"
    """Name of the default workspace created on first startup."""

    def __init__(self):
        """
        Initialize the engine with applicators set to ``None``.

        Applicators are instantiated in :meth:`initialize`
        after the plugin scan.
        """
        super().__init__()

        self.discovery           = PluginDiscovery()
        self.config_io           = ConfigIO()
        self.registry            = {}
        self.current_perspective = None

        self.dock_applicator    = None
        self.toolbar_applicator = None
        self.state_capture      = None

        #: Active dock→toolbar signal connections, keyed by dock name.
        #: Lets :meth:`_connect_dock_toolbar_links` be called repeatedly
        #: without stacking duplicate connections or severing unrelated
        #: ones via a blind ``disconnect()``.
        self._dock_toolbar_connections = {}

    # ─────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────

    def initialize(self):
        """
        Initialize the engine at plugin startup.

        Performs in order:

        1. Scan installed QGIS plugins.
        2. Instantiate applicators.
        3. Create default ``QGIS`` workspace if absent.
        4. Connect dock ↔ toolbar links.
        5. Connect to :attr:`ConfigIO.configChanged` signal.
        """
        self.registry = self.discovery.scan()

        self.dock_applicator    = DockApplicator(self.discovery)
        self.toolbar_applicator = ToolbarApplicator(self.discovery)
        self.state_capture      = StateCapture(self.discovery)

        self._ensure_default_perspective()
        self._connect_dock_toolbar_links()

        self.config_io.configChanged.connect(self._on_config_changed)

    def _on_config_changed(self):
        """
        Called when ``user.psp.json`` is modified from outside.

        Emits :attr:`perspectiveChanged` with the special value
        ``"__reload__"`` to trigger a UI refresh without
        applying a workspace.
        """
        self.perspectiveChanged.emit("__reload__")

    def _ensure_default_perspective(self):
        """
        Create the default ``QGIS`` workspace if absent or empty.

        Checks that the workspace contains at least one visible widget.
        If not, captures the current QGIS interface state and saves
        it as the default workspace.

        .. note::
            The ``QGIS`` workspace is protected against deletion
            in the user interface.
        """
        existing = self.config_io.load(self.DEFAULT_PERSPECTIVE_NAME)

        if existing:
            has_visible = any(
                item.get("visible")
                for plugin_data in existing.get("plugins", {}).values()
                for key in ["docks", "toolbars"]
                for item in plugin_data.get(key, [])
            )
            if has_visible:
                return

        self.registry      = self.discovery.scan()
        self.state_capture = StateCapture(self.discovery)
        data               = self.state_capture.capture(
            self.DEFAULT_PERSPECTIVE_NAME
        )
        self.config_io.save(self.DEFAULT_PERSPECTIVE_NAME, data)

    # ─────────────────────────────────────────────
    # WORKSPACES — LIST
    # ─────────────────────────────────────────────

    def list_perspectives(self) -> list:
        """
        Return the list of all workspace names.

        Includes both user and plugin workspaces.

        :return: List of workspace names.
        :rtype: list[str]
        """
        return self.config_io.list_all()

    def list_perspectives_merged(self) -> list:
        """
        Alias for :meth:`list_perspectives`.

        Kept for compatibility with toolbar calls.

        :return: List of workspace names.
        :rtype: list[str]
        """
        return self.config_io.list_all_merged()

    # ─────────────────────────────────────────────
    # WORKSPACES — CREATE
    # ─────────────────────────────────────────────

    def add_perspective(self, name: str) -> bool:
        """
        Create a new workspace by capturing the current QGIS state.

        Rescans plugins before capture to ensure valid Qt references.

        :param name: Name of the new workspace.
        :type name: str
        :return: ``True`` if created, ``False`` if name already exists.
        :rtype: bool
        """
        if name in self.config_io.list_all():
            return False

        self.registry      = self.discovery.scan()
        self.state_capture = StateCapture(self.discovery)

        data = self.state_capture.capture(name)
        self.config_io.save(name, data)
        return True

    # ─────────────────────────────────────────────
    # WORKSPACES — APPLY
    # ─────────────────────────────────────────────

    def apply(self, name: str):
        """
        Load and apply a workspace by name.

        Delegates to :meth:`_apply_data` after loading ``name`` from
        :attr:`config_io`. Marks ``name`` as the active workspace and
        emits :attr:`perspectiveChanged` on success.

        :param name: Name of the workspace to apply.
        :type name: str
        """
        data = self.config_io.load(name)
        if not data:
            return
        self._apply_data(data, perspective_name=name)

    def apply_preview(self, data: dict):
        """
        Apply a workspace dictionary directly, bypassing
        :attr:`config_io` entirely.

        Used by the management dialog's "Apply" button so unsaved
        edits (visibility, area, line, order...) can be previewed on
        the real QGIS interface before being saved. Unlike
        :meth:`apply`, this does **not** change
        :attr:`current_perspective` or emit :attr:`perspectiveChanged`
        — the previewed data isn't a named, persisted workspace.

        :param data: Workspace dictionary, same shape as what
            :meth:`~perspective_manager.ui.main_window.MainWindow.
            _build_data_from_tree` produces.
        :type data: dict
        """
        self._apply_data(data, perspective_name=None)

    def _apply_data(self, data: dict, perspective_name):
        """
        Apply a workspace dictionary to the QGIS interface.

        Performs, in order:

        0. Restore ``window_state`` (CHANGE 2), if present — a
           geometry baseline only, applied before anything else so
           it never overrides the explicit passes that follow.
        1. Hide all docks and toolbars.
        2. Apply dock configuration.
        3. Apply toolbar configuration.
        4. Show or hide the QGIS menu bar.

        :param data: Workspace dictionary to apply.
        :type data: dict
        :param perspective_name: Name to record as the active
            workspace and emit via :attr:`perspectiveChanged`, or
            ``None`` to apply without marking anything as active
            (used by :meth:`apply_preview`).
        :type perspective_name: str or None
        """
        # Rescan to get valid Qt references
        self.registry           = self.discovery.scan()
        self.dock_applicator    = DockApplicator(self.discovery)
        self.toolbar_applicator = ToolbarApplicator(self.discovery)
        self.state_capture      = StateCapture(self.discovery)

        # Re-link dock↔toolbar pairs — widgets created after plugin
        # startup (e.g. the CAD dock on its first use) would otherwise
        # never get connected, leaving their toolbar stuck ignoring
        # workspace switches.
        self._connect_dock_toolbar_links()

        main_win = iface.mainWindow()
        main_win.setUpdatesEnabled(False)

        try:
            # CHANGE 2 — restore the raw Qt window state (if this
            # workspace has one) as a high-fidelity baseline BEFORE
            # the 4 passes below: it recovers splitter sizes,
            # floating geometry and tab order that the plugin's own
            # area/line/order model can't represent, so the "QGIS"
            # default perspective matches the original layout more
            # closely.
            #
            # Deliberately restored FIRST, not after the 4 passes as
            # originally proposed: doing it last would silently
            # overwrite every perspective's explicit area/line/order/
            # visibility on every apply (every capture stores a
            # window_state), which would make Line/Order edits
            # (CHANGE 3) appear to do nothing. Restoring it first
            # means it only ever supplies a baseline — the passes
            # below always have the final say.
            window_state = data.get("window_state")
            if window_state:
                try:
                    main_win.restoreState(
                        QByteArray.fromBase64(window_state.encode("ascii"))
                    )
                except Exception as e:
                    print(f"[Engine] Could not restore window_state: {e}")

            # Pass 1 — hide all
            self._hide_all()

            # Pass 2 — apply docks
            for plugin_name, plugin_data in data.get("plugins", {}).items():
                self.dock_applicator.apply(
                    plugin_name,
                    plugin_data.get("docks", [])
                )

            # Pass 3 — apply toolbars
            all_toolbars = {
                plugin_name: plugin_data.get("toolbars", [])
                for plugin_name, plugin_data in data.get(
                    "plugins", {}
                ).items()
            }
            self.toolbar_applicator.apply_all(all_toolbars)

            # Pass 4 — menu bar
            show_menu_bar = data.get("show_menu_bar", True)
            iface.mainWindow().menuBar().setVisible(show_menu_bar)

            if perspective_name is not None:
                self.current_perspective = perspective_name
                self.perspectiveChanged.emit(perspective_name)

        except Exception as e:
            label = perspective_name or data.get("name", "?")
            print(f"[Engine] Error applying workspace '{label}': {e}")

        finally:
            main_win.setUpdatesEnabled(True)

    def _hide_all(self):
        """
        Hide all docks and toolbars from the QGIS interface.

        Respects exclusions:

        - :data:`EXCLUDED_TOOLBARS` — never hidden.
        - :data:`LINKED_TOOLBARS` — managed automatically by their dock.

        Docks linked to a toolbar (via :meth:`_connect_dock_toolbar_links`)
        automatically propagate their visibility to their associated toolbar.
        """
        for plugin_data in self.registry.values():

            # Hide docks
            for dock_info in plugin_data.get("docks", []):
                dock = dock_info["object"]
                if not is_valid(dock):
                    continue
                try:
                    dock.setVisible(False)
                except RuntimeError:
                    pass

            # Hide toolbars
            for tb_info in plugin_data.get("toolbars", []):
                tb = tb_info["object"]

                if tb_info["name"] in EXCLUDED_TOOLBARS:
                    continue
                if tb_info["name"] in LINKED_TOOLBARS:
                    continue
                if not is_valid(tb):
                    continue
                try:
                    tb.setVisible(False)
                except RuntimeError:
                    pass

    # ─────────────────────────────────────────────
    # WORKSPACES — SAVE
    # ─────────────────────────────────────────────

    def save(self, name: str):
        """
        Capture the current QGIS interface state and save it.

        :param name: Name of the workspace to update.
        :type name: str
        """
        data = self.state_capture.capture(name)
        self.config_io.save(name, data)

    def save_from_data(self, name: str, data: dict):
        """
        Save a workspace from a dictionary.

        Used by the user interface after manual modification
        via :class:`~perspective_manager.ui.main_window.MainWindow`.

        :param name: Name of the workspace.
        :type name: str
        :param data: Complete workspace dictionary.
        :type data: dict
        """
        self.config_io.save(name, data)

    # ─────────────────────────────────────────────
    # WORKSPACES — DELETE / RENAME
    # ─────────────────────────────────────────────

    def delete(self, name: str):
        """
        Delete a workspace.

        Resets :attr:`current_perspective` if the deleted workspace
        was the active one.

        :param name: Name of the workspace to delete.
        :type name: str
        """
        self.config_io.delete(name)
        if self.current_perspective == name:
            self.current_perspective = None

    def rename(self, old_name: str, new_name: str):
        """
        Rename a workspace.

        Updates :attr:`current_perspective` if the renamed workspace
        was the active one.

        :param old_name: Current name of the workspace.
        :type old_name: str
        :param new_name: New name of the workspace.
        :type new_name: str
        """
        self.config_io.rename(old_name, new_name)
        if self.current_perspective == old_name:
            self.current_perspective = new_name

    # ─────────────────────────────────────────────
    # REGISTRY ACCESS
    # ─────────────────────────────────────────────

    def get_registry(self) -> dict:
        """
        Return the discovered widget registry.

        Used by the user interface to populate
        dock and toolbar trees.

        :return: Registry of plugins and their widgets.
        :rtype: dict
        """
        return self.registry

    def get_current_perspective(self) -> str:
        """
        Return the name of the currently active workspace.

        :return: Name of the active workspace, or ``None``.
        :rtype: str or None
        """
        return self.current_perspective

    # ─────────────────────────────────────────────
    # DOCK ↔ TOOLBAR LINKS
    # ─────────────────────────────────────────────

    def _connect_dock_toolbar_links(self):
        """
        Connect Qt signals to synchronize toolbar visibility
        with their associated dock.

        When a dock is shown or hidden, its linked toolbar
        follows automatically via the ``visibilityChanged`` signal.

        **Configured links:**

        .. code-block:: text

            Browser              → mBrowserToolbar
            Browser2             → mBrowserToolbar
            GPSInformation       → mGpsToolBar
            BookmarksDockWidget  → mBookmarkToolbar
            ProcessingToolbox    → processingToolbar

        .. note::
            Safe to call repeatedly — reconnecting a dock only
            disconnects this method's own previous connection for
            that dock (tracked in :attr:`_dock_toolbar_connections`),
            never other slots that may be connected to the same
            signal (e.g. QGIS's own internal handlers).

        .. note::
            Any link whose dock or toolbar isn't found yet (widgets
            QGIS creates lazily, or a mismatched ``objectName``) is
            logged via ``print`` and skipped — it will be retried on
            the next call (see :meth:`apply`).
        """
        main_win = iface.mainWindow()

        LINKS = {
            "Browser":                 "mBrowserToolbar",
            "Browser2":                "mBrowserToolbar",
            "GPSInformation":          "mGpsToolBar",
            "BookmarksDockWidget":     "mBookmarkToolbar",
            "ProcessingToolbox":       "processingToolbar",
        }

        # Build toolbar index (first occurrence only)
        toolbar_index = {}
        for tb in main_win.findChildren(QToolBar):
            name = tb.objectName()
            if name and name not in toolbar_index:
                toolbar_index[name] = tb

        # Build dock index
        dock_index = {}
        for dock in main_win.findChildren(QDockWidget):
            name = dock.objectName()
            if name and name not in dock_index:
                dock_index[name] = dock

        # Connect links
        for dock_name, toolbar_name in LINKS.items():
            dock    = dock_index.get(dock_name)
            toolbar = toolbar_index.get(toolbar_name)

            if not dock or not toolbar:
                print(
                    f"[Engine] Dock/toolbar link not found: "
                    f"'{dock_name}' -> '{toolbar_name}' "
                    f"(dock={'found' if dock else 'MISSING'}, "
                    f"toolbar={'found' if toolbar else 'MISSING'})"
                )
                continue

            # Disconnect only this method's own previous slot for
            # this dock, if any — never a blind disconnect().
            previous_slot = self._dock_toolbar_connections.get(dock_name)
            if previous_slot is not None:
                try:
                    dock.visibilityChanged.disconnect(previous_slot)
                except (TypeError, RuntimeError):
                    pass

            slot = lambda visible, tb=toolbar: tb.setVisible(visible)
            dock.visibilityChanged.connect(slot)
            self._dock_toolbar_connections[dock_name] = slot