# coding: utf-8

"""
Main module of the QWorkspace Switcher QGIS plugin.

This module provides the :class:`PerspectiveManager` class, the entry
point of the QGIS plugin. It manages the plugin lifecycle (initialization,
graphical interface, unloading) and the workspace toolbar.

**Toolbar structure:**

.. code-block:: text

    ┌──────────────────────────────────────────────────────┐
    │ [⚙] │ | │ [QGIS] │ [Field survey ▼] │ [Meshing]     │
    └──────────────────────────────────────────────────────┘
      │         │              │                    │
    Open      Sepa-       Simple button       Plugin button
    MainWindow rator      (no menu)           (with menu ▼)

**Configuration files:**

- ``perspectives/user.psp.json`` — user workspaces.
- ``<plugin>/<plugin>.psp.json`` — workspaces declared by plugins.

:author: Adnan Benaboud — CNR
"""

import os

from qgis.PyQt.QtWidgets import (
    QAction, QToolBar, QToolButton,
    QMenu, QInputDialog, QMessageBox
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QTimer

from .core.perspective_engine import PerspectiveEngine
from .core.plugin_discovery import is_valid
from .ui.main_window import MainWindow


class QWorkspaceSwitcher:
    """
    Entry point of the QWorkspace Switcher QGIS plugin.

    Manages the plugin lifecycle, the QGIS toolbar and the
    synchronization between the user interface and the engine.

    **Responsibilities:**

    - Initialize and unload the plugin (``initGui`` / ``unload``).
    - Create and maintain the ``QWorkspace Switcher`` toolbar.
    - Create one :class:`QToolButton` per workspace.
    - Open :class:`~perspective_manager.ui.main_window.MainWindow`
      on demand.
    - Refresh the toolbar when the configuration changes.

    :example:

    .. code-block:: python

        # Automatically called by QGIS when loading the plugin
        manager = PerspectiveManager(iface)
        manager.initGui()
    """

    def __init__(self, iface):
        """
        Initialize the manager with the QGIS interface.

        :param iface: Main QGIS interface.
        :type iface: QgisInterface
        """
        self.iface               = iface
        self.plugin_dir          = os.path.dirname(__file__)
        self.first_start         = True
        self.main_window         = None
        self.engine              = None
        self.toolbar             = None
        self.perspective_actions = {}
        self.perspective_buttons = {}

    def initGui(self):
        """
        Initialize the plugin graphical interface.

        - Creates and initializes the :class:`PerspectiveEngine`.
        - Creates the ``QWorkspace Switcher`` toolbar.
        - Adds the action to open the :class:`MainWindow`.
        - Creates workspace buttons via :meth:`_refresh_toolbar`.
        - Connects perspective change and configuration
          modification signals.
        - Installs the ``Ctrl+Shift+M`` shortcut to restore
          the QGIS menu bar in case of emergency.
        """
        self.engine = PerspectiveEngine()
        self.engine.initialize()

        # Create the main toolbar
        self.toolbar = QToolBar("QWorkspace Switcher")
        self.toolbar.setObjectName("QWorkspaceSwitcherToolbar")
        self.iface.addToolBar(self.toolbar)

        # Button to open the MainWindow
        self.action_open = QAction(
            QIcon(os.path.join(self.plugin_dir, "icon.png")),
            "Manage workspaces",
            self.iface.mainWindow()
        )
        self.action_open.triggered.connect(self.run)
        self.toolbar.addAction(self.action_open)
        self.iface.addPluginToMenu(
            "QWorkspace Switcher", self.action_open
        )

        self.toolbar.addSeparator()
        self._refresh_toolbar()

        # Connect signals
        self.engine.perspectiveChanged.connect(
            self._on_perspective_changed
        )
        self.engine.config_io.configChanged.connect(
            self._on_config_file_changed
        )

        # Emergency shortcut to restore the QGIS menu bar
        from qgis.PyQt.QtWidgets import QShortcut
        from qgis.PyQt.QtGui import QKeySequence
        self._shortcut_menu = QShortcut(
            QKeySequence("Ctrl+Shift+M"),
            self.iface.mainWindow()
        )
        self._shortcut_menu.activated.connect(
            lambda: self.iface.mainWindow().menuBar().setVisible(True)
        )

    def unload(self):
        """
        Unload the plugin and restore the QGIS interface.

        - Restores the QGIS menu bar (visible).
        - Removes the entry from the Plugins menu.
        - Removes the toolbar.
        - Closes the :class:`MainWindow` if open.
        """
        self.iface.mainWindow().menuBar().setVisible(True)

        self.iface.removePluginMenu(
            "QWorkspace Switcher", self.action_open
        )
        if self.toolbar:
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.main_window:
            self.main_window.close()
        del self.action_open

    def run(self):
        """
        Open the main :class:`MainWindow`.

        Creates the window on first call (``first_start``),
        then re-displays it on subsequent calls.
        """
        if self.first_start:
            self.first_start = False
            self.main_window = MainWindow(
                engine=self.engine,
                parent=self.iface.mainWindow()
            )
            self.main_window.perspectiveSaved.connect(
                self._refresh_toolbar
            )
        self.main_window.show()
        self.main_window.raise_()

    # ─────────────────────────────────────────────
    # TOOLBAR
    # ─────────────────────────────────────────────

    def _is_toolbar_valid(self) -> bool:
        """
        Check that the Qt toolbar is still valid in memory.

        :return: ``True`` if the toolbar is valid, ``False`` otherwise.
        :rtype: bool
        """
        if self.toolbar is None:
            return False
        try:
            self.toolbar.objectName()
            return True
        except RuntimeError:
            return False

    def _refresh_toolbar(self):
        """
        Recreate all workspace buttons in the toolbar.

        Removes existing buttons and recreates one
        :class:`QToolButton` per workspace from ``self._cfg``.

        **Button styles:**

        - ``text`` → text only.
        - ``icon`` → icon only.
        - ``icon_text`` → icon on the left + text.
        - ``text_icon`` → text on the left + icon on the right
          (via ``Qt.RightToLeft``).

        **Dropdown menu:**

        - If the workspace has ``dropdown_menus`` →
          button with arrow ``▼`` (``MenuButtonPopup``).
        - Otherwise → simple button (``DelayedPopup``).
        """
        if not self._is_toolbar_valid():
            return

        # Remove existing buttons
        for action in list(self.perspective_actions.values()):
            try:
                self.toolbar.removeAction(action)
            except RuntimeError:
                pass

        self.perspective_actions.clear()
        self.perspective_buttons.clear()

        for name in self.engine.config_io.list_all_merged():
            data           = self.engine.config_io.load(name)
            style          = data.get("button_style", "text")
            icon_path      = data.get("icon", "")
            dropdown_menus = data.get("dropdown_menus", [])
            has_dropdown   = bool(dropdown_menus)

            btn = QToolButton()
            btn.setToolTip(f"Workspace: {name}")
            btn.setText(name)

            # Button icon
            if icon_path and os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))

            # Display style
            style_map = {
                "icon":      Qt.ToolButtonIconOnly,
                "icon_text": Qt.ToolButtonTextBesideIcon,
                "text":      Qt.ToolButtonTextOnly,
                "text_icon": Qt.ToolButtonTextBesideIcon,
            }
            btn.setToolButtonStyle(
                style_map.get(style, Qt.ToolButtonTextOnly)
            )

            # text_icon → icon on the right via RTL direction
            if style == "text_icon":
                btn.setLayoutDirection(Qt.RightToLeft)
            else:
                btn.setLayoutDirection(Qt.LeftToRight)

            # Dropdown or simple button mode
            if has_dropdown:
                menu = self._build_perspective_menu(name)
                btn.setMenu(menu)
                btn.setPopupMode(QToolButton.MenuButtonPopup)
            else:
                btn.setPopupMode(QToolButton.DelayedPopup)

            btn.clicked.connect(
                lambda checked, n=name: self.engine.apply(n)
            )
            btn.setCheckable(True)
            if self.engine.get_current_perspective() == name:
                btn.setChecked(True)

            action = self.toolbar.addWidget(btn)
            self.perspective_actions[name] = action
            self.perspective_buttons[name] = btn

    def _on_config_file_changed(self):
        """
        Called when ``user.psp.json`` is modified from outside.

        Uses a delay via :class:`QTimer` to avoid conflicts
        with ongoing write operations on the Qt toolbar.
        """
        QTimer.singleShot(300, self._safe_refresh)

    def _safe_refresh(self):
        """
        Safely refresh the toolbar and MainWindow.

        Checks toolbar validity before any operation.
        Protects against Qt errors if the toolbar has been destroyed.
        """
        if not self._is_toolbar_valid():
            return

        try:
            self._refresh_toolbar()
        except RuntimeError:
            return

        if self.main_window and self.main_window.isVisible():
            try:
                self.main_window._refresh_list()
                current = self.main_window.inputName.text().strip()
                if current:
                    self.main_window._load_perspective_in_tree(current)
            except RuntimeError:
                pass

    def _on_perspective_changed(self, name: str):
        """
        Synchronize the pressed state of the toolbar buttons.

        Presses the active workspace button and releases
        the others. Ignores the special value ``"__reload__"``.

        :param name: Name of the applied workspace,
            or ``"__reload__"`` for a simple refresh.
        :type name: str
        """
        if name == "__reload__":
            return
        for perspective_name, btn in self.perspective_buttons.items():
            try:
                btn.setChecked(perspective_name == name)
            except RuntimeError:
                pass

    # ─────────────────────────────────────────────
    # DROPDOWN MENU
    # ─────────────────────────────────────────────

    def _build_perspective_menu(self, name: str) -> QMenu:
        """
        Build the dropdown menu for a workspace.

        Loads ``dropdown_menus`` from ``self._cfg`` and
        copies the :class:`QMenu` from the corresponding plugins.

        Handles compatibility with the old structure
        (list of strings with ``dropdown_plugin``).

        :param name: Name of the workspace.
        :type name: str
        :return: Dropdown menu ready to be attached to the button.
        :rtype: QMenu
        """
        menu           = QMenu()
        data           = self.engine.config_io.load(name)
        dropdown_menus = data.get("dropdown_menus", [])

        # Compatibility with old structure (list of strings)
        if dropdown_menus and isinstance(dropdown_menus[0], str):
            old_plugin     = data.get("dropdown_plugin", "")
            dropdown_menus = [
                {"plugin": old_plugin, "menu": m}
                for m in dropdown_menus
            ]

        if dropdown_menus:
            self._append_plugin_menus(menu, dropdown_menus)

        return menu

    def _append_plugin_menus(self, menu: QMenu,
                             dropdown_menus: list):
        """
        Copy selected plugin menus into the dropdown menu.

        Groups menus by plugin with a separator and a label
        per plugin. Ignores invalid or missing menus.

        :param menu: Target menu to add submenus to.
        :type menu: QMenu
        :param dropdown_menus: List of ``{"plugin": str, "menu": str}``.
        :type dropdown_menus: list[dict]
        """
        registry     = self.engine.get_registry()
        plugins_seen = set()

        for item in dropdown_menus:
            plugin_name = item["plugin"]
            menu_name   = item["menu"]

            plugin_data = registry.get(plugin_name, {})
            all_menus   = plugin_data.get("menus", [])

            menu_info = next(
                (m for m in all_menus if m["name"] == menu_name),
                None
            )
            if not menu_info:
                continue

            original_menu = menu_info["object"]
            if not is_valid(original_menu):
                continue

            # Add separator + plugin label for first menu of plugin
            if plugin_name not in plugins_seen:
                plugins_seen.add(plugin_name)
                if menu.actions():
                    menu.addSeparator()
                label = QAction(
                    f"── {plugin_data.get('display_name', plugin_name)} ──",
                    menu
                )
                label.setEnabled(False)
                menu.addAction(label)

            copied = self._copy_menu(original_menu, menu)
            menu.addMenu(copied)

    def _copy_menu(self, source_menu: QMenu, parent) -> QMenu:
        """
        Recursively copy a :class:`QMenu`.

        Creates a new menu with the same actions as the source.
        Copied actions trigger the original plugin actions
        via ``original_action.trigger()``.

        :param source_menu: Source menu to copy.
        :type source_menu: QMenu
        :param parent: Parent widget of the copied menu.
        :return: Copy of the source menu.
        :rtype: QMenu
        """
        copied_menu = QMenu(source_menu.title(), parent)
        copied_menu.setIcon(source_menu.icon())

        for action in source_menu.actions():
            if action.isSeparator():
                copied_menu.addSeparator()

            elif action.menu():
                sub = self._copy_menu(action.menu(), copied_menu)
                copied_menu.addMenu(sub)

            else:
                new_action = QAction(
                    action.icon(),
                    action.text(),
                    copied_menu
                )
                new_action.setEnabled(action.isEnabled())
                new_action.setCheckable(action.isCheckable())
                new_action.setChecked(action.isChecked())
                new_action.setToolTip(action.toolTip())

                original = action
                new_action.triggered.connect(
                    lambda checked, a=original: a.trigger()
                )
                copied_menu.addAction(new_action)

        return copied_menu

    # ─────────────────────────────────────────────
    # TOOLBAR ACTIONS
    # ─────────────────────────────────────────────

    def _open_perspective(self, name: str):
        """
        Open the :class:`MainWindow` and select a workspace.

        :param name: Name of the workspace to select.
        :type name: str
        """
        self.run()
        if self.main_window:
            items = self.main_window.listPerspectives.findItems(
                name, Qt.MatchExactly
            )
            if items:
                self.main_window.listPerspectives.setCurrentItem(
                    items[0]
                )

    def _duplicate_perspective(self, name: str):
        """
        Duplicate a workspace from the toolbar.

        :param name: Name of the workspace to duplicate.
        :type name: str
        """
        new_name, ok = QInputDialog.getText(
            None, "Duplicate workspace", "New name:",
            text=f"{name} - copy"
        )
        if ok and new_name.strip():
            data         = self.engine.config_io.load(name)
            data["name"] = new_name.strip()
            self.engine.save_from_data(new_name.strip(), data)
            self._refresh_toolbar()
            if self.main_window:
                self.main_window._refresh_list()

    def _delete_perspective(self, name: str):
        """
        Delete a workspace from the toolbar after confirmation.

        The ``QGIS`` workspace is protected against deletion.

        :param name: Name of the workspace to delete.
        :type name: str
        """
        if name == "QGIS":
            return

        reply = QMessageBox.question(
            None, "Delete workspace",
            f"Delete workspace '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.engine.delete(name)
            self._refresh_toolbar()
            if self.main_window:
                self.main_window._refresh_list()
                self.main_window._reset_tree()
                self.main_window._set_editor_visible(False)