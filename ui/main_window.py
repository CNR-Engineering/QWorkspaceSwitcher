# coding: utf-8

"""
Main interface module of the QWorkspaceSwitcher plugin.

This module provides the :class:`MainWindow` class, a Qt dialog
allowing the user to create, modify, delete and apply
QGIS workspaces.

**Interface structure:**

.. code-block:: text

    ┌──────────────────────────────────────────────────────┐
    │  Workspace list          │  Workspace editor         │
    │  ─────────────────────   │  ──────────────────────── │
    │  • QGIS                  │  Name: [____________]      │
    │  • Field survey          │  Button configuration      │
    │  • Visualization         │  ┌──────────────────────┐  │
    │                          │  │ Panels  │ Toolbars    │  │
    │  [+ New]                 │  │ Menus                │  │
    │  [Duplicate]             │  └──────────────────────┘  │
    │  [Delete]                │  [Apply]  [Save]           │
    └──────────────────────────────────────────────────────┘

**Toolbars hidden in the tree** (linked to a dock or without valid name):

- ``QToolBar``
- ``mBrowserToolbar``
- ``mGpsToolBar``
- ``mBookmarkToolbar``
- ``processingToolbar``

:author: Adnan Benaboud — CNR
"""

import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QDialog, QTreeWidgetItem, QComboBox,
    QInputDialog, QMessageBox, QSpinBox
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon

from ..applicators.state_capture import StateCapture


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'main_window.ui')
)

#: Workspaces protected against deletion.
PROTECTED_PERSPECTIVES = ["QGIS"]

#: Toolbars hidden in the tree — linked to a dock or without valid name.
HIDDEN_TOOLBARS = {
    "QToolBar",
    "mBrowserToolbar",
    "mGpsToolBar",
    "mBookmarkToolbar",
    "processingToolbar",
}


class MainWindow(QDialog, FORM_CLASS):
    """
    Main interface of the QWorkspaceSwitcher plugin.

    Allows creating, modifying, deleting, duplicating and applying
    QGIS workspaces. Loads the ``.ui`` file via
    :func:`uic.loadUiType`.

    **Signals:**

    - :attr:`perspectiveSaved` — emitted after each save or capture.

    :example:

    .. code-block:: python

        window = MainWindow(engine=engine, parent=iface.mainWindow())
        window.show()
    """

    perspectiveSaved = pyqtSignal()
    """Signal emitted after each workspace save or capture."""

    def __init__(self, engine, parent=None):
        """
        Initialize the main window.

        Builds dynamic widgets, connects signals,
        fills the workspace list and widget trees.

        :param engine: Main plugin engine.
        :type engine: PerspectiveEngine
        :param parent: Qt parent widget.
        :type parent: QWidget or None
        """
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("QWorkspaceSwitcher")
        self.engine             = engine
        self._current_icon_path = ""

        #: Per-tree, per-plugin snapshot of which children were
        #: checked right before their root was unchecked. Lets a
        #: root checkbox restore exactly that selection instead of
        #: force-checking every child. Keyed by
        #: ``(id(tree), plugin_name)``.
        self._root_snapshot = {}

        # Connect Configuration signals for title indicator
        self.engine.config_io._cfg.sgl_unsaved.connect(
            lambda: self.setWindowTitle("QWorkspaceSwitcher *")
        )
        self.engine.config_io._cfg.sgl_saved.connect(
            lambda: self.setWindowTitle("QWorkspaceSwitcher")
        )

        # Build dynamic widgets before _set_editor_visible
        self._build_style_widgets()

        # Hide central panel until a workspace is selected
        self._set_editor_visible(False)

        # Connect buttons
        self.btnAdd.clicked.connect(self._on_add)
        self.btnDuplicate.clicked.connect(self._on_duplicate)
        self.btnDelete.clicked.connect(self._on_delete)
        self.btnApply.clicked.connect(self._on_apply)
        self.btnSave.clicked.connect(self._on_save)
        self.btnCapture.clicked.connect(self._on_capture)
        self.pushButton_expor_perspectives.clicked.connect(
            self._export_perspectives_json
        )

        # Fill the list and trees
        self._refresh_list()
        self._populate_tree()

        # Connect list selection signal
        self.listPerspectives.currentTextChanged.connect(
            self._on_perspective_selected
        )

    # ─────────────────────────────────────────────
    # BUTTON STYLE CONFIGURATION
    # ─────────────────────────────────────────────

    def _build_style_widgets(self):
        """
        Configure style widgets created in Qt Designer.

        Connects signals and initializes default states for:

        - ``checkBox_icon`` — enables/disables icon selection.
        - ``comboBox_emplacement`` — toolbar button style.
        - ``pushButton_importIcon`` — opens icon file selector.
        - ``checkBox_ajoutMenu`` — enables/disables dropdown menu.
        - ``treeWidget_menu`` — menu selection tree.
        - ``checkBox_menuBar`` — shows/hides QGIS menu bar.
        """
        # Icon
        self.checkBox_icon.stateChanged.connect(
            self._on_icon_checkbox_changed
        )
        self.comboBox_emplacement.addItems(
            ["text", "icon", "icon_text", "text_icon"]
        )
        self.comboBox_emplacement.setToolTip(
            "<b>Button style:</b><br>"
            "• <b>text</b> → text only<br>"
            "• <b>icon</b> → icon only<br>"
            "• <b>icon_text</b> → icon on left + text<br>"
            "• <b>text_icon</b> → text on left + icon on right"
        )
        self.comboBox_emplacement.setEnabled(False)
        self.pushButton_importIcon.setEnabled(False)
        self.pushButton_importIcon.clicked.connect(self._on_choose_icon)

        # Dropdown menu
        self.checkBox_ajoutMenu.stateChanged.connect(
            self._on_menu_checkbox_changed
        )
        self.treeWidget_menu.setEnabled(False)

        # QGIS menu bar
        self.checkBox_menuBar.setChecked(True)
        self.checkBox_menuBar.setToolTip(
            "Show or hide the QGIS menu bar "
            "when this workspace is applied"
        )

    def _on_icon_checkbox_changed(self, state: int):
        """
        Enable or disable icon selection widgets.

        :param state: Checkbox state (``Qt.CheckState.Checked`` or
            ``Qt.CheckState.Unchecked``).
        :type state: int
        """
        enabled = state == Qt.CheckState.Checked
        self.comboBox_emplacement.setEnabled(enabled)
        self.pushButton_importIcon.setEnabled(enabled)
        if not enabled:
            self._current_icon_path = ""
            self.pushButton_importIcon.setIcon(QIcon())
            self.pushButton_importIcon.setText("Choose icon")

    def _on_menu_checkbox_changed(self, state: int):
        """
        Enable or disable the dropdown menu selection tree.

        Unchecks all menus when the checkbox is disabled.

        :param state: Checkbox state (``Qt.CheckState.Checked`` or
            ``Qt.CheckState.Unchecked``).
        :type state: int
        """
        self.treeWidget_menu.setEnabled(state == Qt.CheckState.Checked)
        if state != Qt.CheckState.Checked:
            self.treeWidget_menu.blockSignals(True)
            for i in range(self.treeWidget_menu.topLevelItemCount()):
                plugin_item = self.treeWidget_menu.topLevelItem(i)
                plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
                for j in range(plugin_item.childCount()):
                    plugin_item.child(j).setCheckState(0, Qt.CheckState.Unchecked)
            self.treeWidget_menu.blockSignals(False)

    def _on_choose_icon(self):
        """
        Open an image file selection dialog.

        Updates :attr:`_current_icon_path` and displays the chosen
        icon on the ``pushButton_importIcon`` button.
        """
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an icon", "",
            "Images (*.png *.jpg *.svg *.ico)"
        )
        if path:
            self._current_icon_path = path
            self.pushButton_importIcon.setIcon(QIcon(path))
            self.pushButton_importIcon.setText(os.path.basename(path))

    # ─────────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────────

    def _export_perspectives_json(self):
        """
        Export ``user.psp.json`` to a location chosen by the user.

        Opens a save dialog and copies the source file
        to the chosen destination.
        """
        from qgis.PyQt.QtWidgets import QFileDialog
        import shutil

        source_path = self.engine.config_io.config_path
        if not os.path.exists(source_path):
            QMessageBox.warning(
                self, "File not found",
                "No workspace configuration file to export."
            )
            return

        dest_path, _ = QFileDialog.getSaveFileName(
            self, "Export workspaces",
            os.path.join(os.path.expanduser("~"), "user.psp.json"),
            "JSON (*.json)"
        )
        if not dest_path:
            return

        try:
            shutil.copy2(source_path, dest_path)
            QMessageBox.information(
                self, "Export successful",
                f"Workspaces exported to:\n{dest_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Export error",
                f"Unable to export the file:\n{e}"
            )

    # ─────────────────────────────────────────────
    # WORKSPACE LIST
    # ─────────────────────────────────────────────

    def _refresh_list(self):
        """
        Reload the workspace list from ``self._cfg``.

        Preserves the current selection if it still exists
        in the updated list.
        """
        current_name = self.inputName.text().strip()

        self.listPerspectives.blockSignals(True)
        self.listPerspectives.clear()
        for name in self.engine.list_perspectives():
            self.listPerspectives.addItem(name)
        self.listPerspectives.blockSignals(False)

        if current_name:
            items = self.listPerspectives.findItems(
                current_name, Qt.MatchFlag.MatchExactly
            )
            if items:
                self.listPerspectives.blockSignals(True)
                self.listPerspectives.setCurrentItem(items[0])
                self.listPerspectives.blockSignals(False)
                self._set_editor_visible(True)

    def _on_perspective_selected(self, name: str):
        """
        Called when the user selects a workspace in the list.

        Updates the name field and loads the workspace into the trees.

        :param name: Name of the selected workspace.
        :type name: str
        """
        if not name:
            self._set_editor_visible(False)
            return
        self.inputName.setText(name)
        self._set_editor_visible(True)
        self._load_perspective_in_tree(name)

    # ─────────────────────────────────────────────
    # TREES
    # ─────────────────────────────────────────────

    def _populate_tree(self):
        """
        Fill the three trees from the plugin registry.

        Calls successively :meth:`_populate_docks_tree`,
        :meth:`_populate_toolbars_tree` and
        :meth:`_populate_menus_tree`.
        """
        self._populate_docks_tree()
        self._populate_toolbars_tree()
        self._populate_menus_tree()

    def _populate_docks_tree(self):
        """
        Fill ``treeDocks`` from the plugin registry.

        Creates one parent node per plugin and one child node
        per dock, with a :class:`QComboBox` for area selection
        in column 2.
        """
        self.treeDocks.clear()
        self.treeDocks.setColumnCount(3)
        self.treeDocks.setHeaderLabels(["Name", "Type", "Area"])
        self.treeDocks.setColumnWidth(0, 220)
        self.treeDocks.setColumnWidth(1, 70)
        self.treeDocks.setColumnWidth(2, 100)

        registry = self.engine.get_registry()

        for plugin_name, plugin_data in registry.items():
            docks = plugin_data.get("docks", [])
            if not docks:
                continue

            plugin_item = QTreeWidgetItem(self.treeDocks)
            plugin_item.setText(0, plugin_data["display_name"])
            plugin_item.setData(0, Qt.ItemDataRole.UserRole, plugin_name)
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            plugin_item.setExpanded(True)

            for dock_info in docks:
                self._add_dock_item(plugin_item, dock_info)

        self.treeDocks.itemChanged.connect(self._on_dock_item_changed)

    def _populate_toolbars_tree(self, perspective_data: dict = None):
        """
        Fill ``treeToolbars`` from the plugin registry.

        Filters toolbars from :data:`HIDDEN_TOOLBARS`. If
        ``perspective_data`` is provided, pre-fills line numbers
        and in-line order from the saved JSON data.

        :param perspective_data: Existing workspace data to initialize
            toolbar lines and order. If ``None``, uses line 1 /
            order 1 by default.
        :type perspective_data: dict or None
        """
        try:
            self.treeToolbars.itemChanged.disconnect()
        except Exception:
            pass

        self.treeToolbars.blockSignals(True)  # ← bloquer avant tout
        self.treeToolbars.clear()
        self.treeToolbars.setColumnCount(3)
        self.treeToolbars.setHeaderLabels(["Name", "Line", "Order"])
        self.treeToolbars.setColumnWidth(0, 300)
        self.treeToolbars.setColumnWidth(1, 60)
        self.treeToolbars.setColumnWidth(2, 60)

        registry = self.engine.get_registry()

        for plugin_name, plugin_data in registry.items():
            toolbars = plugin_data.get("toolbars", [])
            if not toolbars:
                continue

            visible_toolbars = [
                tb for tb in toolbars
                if tb["name"] not in HIDDEN_TOOLBARS and tb["name"]
            ]
            if not visible_toolbars:
                continue

            saved_toolbars = {}
            if perspective_data:
                saved_toolbars = {
                    t["name"]: t
                    for t in perspective_data.get(
                        "plugins", {}
                    ).get(plugin_name, {}).get("toolbars", [])
                }

            plugin_item = QTreeWidgetItem(self.treeToolbars)
            plugin_item.setText(0, plugin_data["display_name"])
            plugin_item.setData(0, Qt.ItemDataRole.UserRole, plugin_name)
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            plugin_item.setExpanded(True)

            for tb_info in visible_toolbars:
                saved = saved_toolbars.get(tb_info["name"], {})
                line  = saved.get("line", tb_info.get("line", 1))
                order = saved.get("order", tb_info.get("order", 1))

                child = QTreeWidgetItem(plugin_item)
                child.setText(0, tb_info["label"])
                child.setData(0, Qt.ItemDataRole.UserRole, tb_info["name"])
                child.setData(1, Qt.ItemDataRole.UserRole, "toolbar")

                spinbox = QSpinBox()
                spinbox.setMinimum(1)
                spinbox.setMaximum(5)
                spinbox.setValue(line)
                spinbox.setToolTip("Line in toolbar area")
                self.treeToolbars.setItemWidget(child, 1, spinbox)

                order_spinbox = QSpinBox()
                order_spinbox.setMinimum(1)
                order_spinbox.setMaximum(20)
                order_spinbox.setValue(order)
                order_spinbox.setToolTip(
                    "Position within the line (1 = leftmost/topmost)"
                )
                self.treeToolbars.setItemWidget(child, 2, order_spinbox)

                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)

                # ← Cocher directement selon visible dans saved
                if perspective_data and saved:
                    state = Qt.CheckState.Checked if saved.get("visible", True) \
                            else Qt.CheckState.Unchecked
                else:
                    # Pas de données → utiliser l'état actuel de la toolbar
                    state = Qt.CheckState.Checked if tb_info.get("visible", False) \
                            else Qt.CheckState.Unchecked
                child.setCheckState(0, state)

            # Mettre à jour la checkbox parent
            checked_count = sum(
                1 for j in range(plugin_item.childCount())
                if plugin_item.child(j).checkState(0) == Qt.CheckState.Checked
            )
            if checked_count == 0:
                plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            elif checked_count == plugin_item.childCount():
                plugin_item.setCheckState(0, Qt.CheckState.Checked)
            else:
                plugin_item.setCheckState(0, Qt.CheckState.PartiallyChecked)

        self.treeToolbars.blockSignals(False)
        self.treeToolbars.itemChanged.connect(self._on_toolbar_item_changed)

    def _populate_menus_tree(self):
        """
        Fill ``treeWidget_menu`` from the plugin registry.

        Creates one parent node per plugin and one child node
        per menu. Stores the plugin name in ``Qt.ItemDataRole.UserRole + 1``
        of each child node for easy retrieval when saving.
        """
        self.treeWidget_menu.clear()
        self.treeWidget_menu.setColumnCount(1)
        self.treeWidget_menu.setHeaderLabels(["Menu"])
        self.treeWidget_menu.setColumnWidth(0, 300)

        registry = self.engine.get_registry()

        for plugin_name, plugin_data in registry.items():
            menus = plugin_data.get("menus", [])
            if not menus:
                continue

            plugin_item = QTreeWidgetItem(self.treeWidget_menu)
            plugin_item.setText(0, plugin_data["display_name"])
            plugin_item.setData(0, Qt.ItemDataRole.UserRole, plugin_name)
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            plugin_item.setExpanded(True)

            for menu_info in menus:
                child = QTreeWidgetItem(plugin_item)
                child.setText(0, menu_info["label"])
                child.setData(0, Qt.ItemDataRole.UserRole, menu_info["name"])
                child.setData(1, Qt.ItemDataRole.UserRole, plugin_name)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)

        self.treeWidget_menu.itemChanged.connect(
            self._on_menu_item_changed
        )

    def _add_dock_item(self, parent_item: QTreeWidgetItem,
                       dock_info: dict) -> QTreeWidgetItem:
        """
        Add a dock node to ``treeDocks``.

        Creates a :class:`QComboBox` for area selection in column 2.

        :param parent_item: Parent node (plugin) in the tree.
        :type parent_item: QTreeWidgetItem
        :param dock_info: Dock information from the registry.
        :type dock_info: dict
        :return: Created child node.
        :rtype: QTreeWidgetItem
        """
        child = QTreeWidgetItem(parent_item)
        child.setText(0, dock_info["label"])
        child.setText(1, "dock")
        child.setData(0, Qt.ItemDataRole.UserRole, dock_info["name"])
        child.setData(1, Qt.ItemDataRole.UserRole, "dock")

        combo = QComboBox()
        combo.addItems(["left", "right", "top", "bottom"])
        idx = combo.findText(dock_info.get("area", "left"))
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self.treeDocks.setItemWidget(child, 2, combo)

        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        child.setCheckState(0, Qt.CheckState.Unchecked)
        return child

    def _add_toolbar_item(self, parent_item: QTreeWidgetItem,
                          tb_info: dict,
                          saved_line: int = 1) -> QTreeWidgetItem:
        """
        Add a toolbar node to ``treeToolbars``.

        Creates a :class:`QSpinBox` for line selection in column 1.

        :param parent_item: Parent node (plugin) in the tree.
        :type parent_item: QTreeWidgetItem
        :param tb_info: Toolbar information from the registry.
        :type tb_info: dict
        :param saved_line: Line number saved in JSON.
            Used to initialize the :class:`QSpinBox`.
        :type saved_line: int
        :return: Created child node.
        :rtype: QTreeWidgetItem
        """
        child = QTreeWidgetItem(parent_item)
        child.setText(0, tb_info["label"])
        child.setData(0, Qt.ItemDataRole.UserRole, tb_info["name"])
        child.setData(1, Qt.ItemDataRole.UserRole, "toolbar")

        spinbox = QSpinBox()
        spinbox.setMinimum(1)
        spinbox.setMaximum(5)
        spinbox.setValue(saved_line)
        spinbox.setToolTip("Line in toolbar area")
        self.treeToolbars.setItemWidget(child, 1, spinbox)

        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        child.setCheckState(0, Qt.CheckState.Unchecked)
        return child

    # ─────────────────────────────────────────────
    # TREE SIGNALS
    # ─────────────────────────────────────────────

    def _on_dock_item_changed(self, item: QTreeWidgetItem,
                              column: int):
        """
        React to a checkbox change in ``treeDocks``.

        A root (plugin) row is handled by
        :meth:`_on_root_checkbox_changed`; a child row updates its
        parent's tri-state checkbox via :meth:`_update_parent_check`.

        :param item: Modified node.
        :type item: QTreeWidgetItem
        :param column: Modified column.
        :type column: int
        """
        if column != 0:
            return
        parent = item.parent()
        if parent is None:
            self._on_root_checkbox_changed(self.treeDocks, item)
            return
        self._update_parent_check(self.treeDocks, parent)

    def _on_toolbar_item_changed(self, item: QTreeWidgetItem,
                                 column: int):
        """
        React to a checkbox change in ``treeToolbars``.

        A root (plugin) row is handled by
        :meth:`_on_root_checkbox_changed`; a child row updates its
        parent's tri-state checkbox via :meth:`_update_parent_check`.

        :param item: Modified node.
        :type item: QTreeWidgetItem
        :param column: Modified column.
        :type column: int
        """
        if column != 0:
            return
        parent = item.parent()
        if parent is None:
            self._on_root_checkbox_changed(self.treeToolbars, item)
            return
        self._update_parent_check(self.treeToolbars, parent)

    def _on_menu_item_changed(self, item: QTreeWidgetItem,
                              column: int):
        """
        React to a checkbox change in ``treeWidget_menu``.

        A root (plugin) row is handled by
        :meth:`_on_root_checkbox_changed`; a child row updates its
        parent's tri-state checkbox via :meth:`_update_parent_check`.

        :param item: Modified node.
        :type item: QTreeWidgetItem
        :param column: Modified column.
        :type column: int
        """
        if column != 0:
            return
        parent = item.parent()
        if parent is None:
            self._on_root_checkbox_changed(self.treeWidget_menu, item)
            return
        self._update_parent_check(self.treeWidget_menu, parent)

    def _on_root_checkbox_changed(self, tree,
                                  plugin_item: QTreeWidgetItem):
        """
        Handle a direct check/uncheck of a plugin's root row.

        Unchecking a root remembers which of its children were
        checked, then unchecks all of them. Checking a root restores
        exactly that remembered set instead of forcing every child
        on — but only once such a set actually exists (i.e. after
        the root has been unchecked at least once this session).
        Before that, there is no "before" to restore, so checking an
        untouched root falls back to checking every child, like an
        ordinary select-all.

        :param tree: Tree the root belongs to.
        :param plugin_item: The root (plugin) node whose checkbox
            was just changed by the user.
        :type plugin_item: QTreeWidgetItem
        """
        plugin_key = plugin_item.data(0, Qt.ItemDataRole.UserRole)
        state      = plugin_item.checkState(0)
        snap_key   = (id(tree), plugin_key)

        tree.blockSignals(True)
        try:
            if state == Qt.CheckState.Unchecked:
                self._root_snapshot[snap_key] = {
                    plugin_item.child(j).data(0, Qt.ItemDataRole.UserRole)
                    for j in range(plugin_item.childCount())
                    if plugin_item.child(j).checkState(0) == Qt.CheckState.Checked
                }
                for j in range(plugin_item.childCount()):
                    plugin_item.child(j).setCheckState(0, Qt.CheckState.Unchecked)
            elif snap_key in self._root_snapshot:
                previously_checked = self._root_snapshot[snap_key]
                for j in range(plugin_item.childCount()):
                    child = plugin_item.child(j)
                    if child.data(0, Qt.ItemDataRole.UserRole) in previously_checked:
                        child.setCheckState(0, Qt.CheckState.Checked)
            else:
                # Never unchecked yet this session — nothing to
                # restore, so behave like an ordinary select-all.
                for j in range(plugin_item.childCount()):
                    plugin_item.child(j).setCheckState(0, Qt.CheckState.Checked)

            # The raw click always lands on Checked/Unchecked — fix
            # the root's own display to match what actually happened
            # to its children (e.g. an empty snapshot restores
            # nothing, so the root should read back as Unchecked).
            total   = plugin_item.childCount()
            checked = sum(
                1 for j in range(total)
                if plugin_item.child(j).checkState(0) == Qt.CheckState.Checked
            )
            if checked == 0:
                plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            elif checked == total:
                plugin_item.setCheckState(0, Qt.CheckState.Checked)
            else:
                plugin_item.setCheckState(0, Qt.CheckState.PartiallyChecked)
        finally:
            tree.blockSignals(False)

    def _update_parent_check(self, tree,
                             parent: QTreeWidgetItem):
        """
        Update the checkbox state of a parent node based on its children.

        - All checked → ``Qt.CheckState.Checked``.
        - None checked → ``Qt.CheckState.Unchecked``.
        - Partially checked → ``Qt.CheckState.PartiallyChecked``.

        :param tree: Tree containing the parent node.
        :param parent: Parent node to update.
        :type parent: QTreeWidgetItem
        """
        total   = parent.childCount()
        checked = sum(
            1 for i in range(total)
            if parent.child(i).checkState(0) == Qt.CheckState.Checked
        )
        tree.blockSignals(True)
        if checked == 0:
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        elif checked == total:
            parent.setCheckState(0, Qt.CheckState.Checked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        tree.blockSignals(False)

    # ─────────────────────────────────────────────
    # LOAD WORKSPACE INTO TREE
    # ─────────────────────────────────────────────

    def _load_perspective_in_tree(self, name: str):
        """
        Load an existing workspace into all trees and widgets.

        Updates:

        - ``checkBox_icon``, ``comboBox_emplacement``,
          ``pushButton_importIcon`` — style and icon.
        - ``checkBox_menuBar`` — menu bar visibility.
        - ``checkBox_ajoutMenu``, ``treeWidget_menu`` — dropdown menus.
        - ``treeDocks`` — panel states.
        - ``treeToolbars`` — toolbar states and lines.

        :param name: Name of the workspace to load.
        :type name: str
        """
        data = self.engine.config_io.load(name)
        if not data:
            self._reset_tree()
            return

        # ── Icon and button style ──────────────────
        icon_path    = data.get("icon", "")
        button_style = data.get("button_style", "text")

        if icon_path:
            self.checkBox_icon.blockSignals(True)
            self.checkBox_icon.setChecked(True)
            self.checkBox_icon.blockSignals(False)
            self._current_icon_path = icon_path
            self.comboBox_emplacement.setEnabled(True)
            self.pushButton_importIcon.setEnabled(True)
            idx = self.comboBox_emplacement.findText(button_style)
            if idx >= 0:
                self.comboBox_emplacement.setCurrentIndex(idx)
            if os.path.exists(icon_path):
                self.pushButton_importIcon.setIcon(QIcon(icon_path))
                self.pushButton_importIcon.setText(
                    os.path.basename(icon_path)
                )
        else:
            self.checkBox_icon.blockSignals(True)
            self.checkBox_icon.setChecked(False)
            self.checkBox_icon.blockSignals(False)
            self._current_icon_path = ""
            self.comboBox_emplacement.setEnabled(False)
            self.pushButton_importIcon.setEnabled(False)
            self.pushButton_importIcon.setIcon(QIcon())
            self.pushButton_importIcon.setText("Choose icon")

        # ── Menu bar ───────────────────────────────
        show_menu_bar = data.get("show_menu_bar", True)
        self.checkBox_menuBar.blockSignals(True)
        self.checkBox_menuBar.setChecked(show_menu_bar)
        self.checkBox_menuBar.blockSignals(False)

        # ── Dropdown menus ─────────────────────────
        dropdown_menus = data.get("dropdown_menus", [])

        # Compatibility with old structure (list of strings)
        if dropdown_menus and isinstance(dropdown_menus[0], str):
            old_plugin     = data.get("dropdown_plugin", "")
            dropdown_menus = [
                {"plugin": old_plugin, "menu": m}
                for m in dropdown_menus
            ]

        has_menus = bool(dropdown_menus)
        self.checkBox_ajoutMenu.blockSignals(True)
        self.checkBox_ajoutMenu.setChecked(has_menus)
        self.checkBox_ajoutMenu.blockSignals(False)
        self.treeWidget_menu.setEnabled(has_menus)

        selected_set = {
            (item["plugin"], item["menu"])
            for item in dropdown_menus
        }

        self.treeWidget_menu.blockSignals(True)
        for i in range(self.treeWidget_menu.topLevelItemCount()):
            plugin_item = self.treeWidget_menu.topLevelItem(i)
            for j in range(plugin_item.childCount()):
                child       = plugin_item.child(j)
                menu_name   = child.data(0, Qt.ItemDataRole.UserRole)
                plugin_name = child.data(1, Qt.ItemDataRole.UserRole)
                if (plugin_name, menu_name) in selected_set:
                    child.setCheckState(0, Qt.CheckState.Checked)
                else:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
        self.treeWidget_menu.blockSignals(False)

        # ── Repopulate treeToolbars with saved lines ──
        self._populate_toolbars_tree(perspective_data=data)

        # ── treeDocks ─────────────────────────────
        registry     = self.engine.get_registry()
        plugin_names = list(registry.keys())

        self.treeDocks.blockSignals(True)
        plugins_with_docks = [
            pn for pn in plugin_names if registry[pn].get("docks")
        ]
        for i in range(self.treeDocks.topLevelItemCount()):
            if i >= len(plugins_with_docks):  # ← protection
                break
            plugin_item = self.treeDocks.topLevelItem(i)
            plugin_name = plugins_with_docks[i]
            plugin_data = data.get("plugins", {}).get(plugin_name, {})
            saved_docks = {
                d["name"]: d for d in plugin_data.get("docks", [])
            }
            for j in range(plugin_item.childCount()):
                child       = plugin_item.child(j)
                widget_name = child.data(0, Qt.ItemDataRole.UserRole)
                saved       = saved_docks.get(widget_name)
                if saved:
                    state = Qt.CheckState.Checked if saved.get("visible", True) \
                            else Qt.CheckState.Unchecked
                    child.setCheckState(0, state)
                    combo = self.treeDocks.itemWidget(child, 2)
                    if combo:
                        idx = combo.findText(saved.get("area", "left"))
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                else:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
        self.treeDocks.blockSignals(False)

    # ─────────────────────────────────────────────
    # RESET TREE
    # ─────────────────────────────────────────────

    def _reset_tree(self):
        """
        Reset all trees and configuration widgets.

        - Unchecks all checkboxes in the three trees.
        - Resets :class:`QComboBox` and :class:`QSpinBox`.
        - Resets icon, menu and menu bar checkboxes.
        - Clears :attr:`_current_icon_path`.
        """
        for tree in [self.treeDocks, self.treeToolbars]:
            tree.blockSignals(True)
            for i in range(tree.topLevelItemCount()):
                plugin_item = tree.topLevelItem(i)
                plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
                for j in range(plugin_item.childCount()):
                    child = plugin_item.child(j)
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                    if tree == self.treeDocks:
                        combo = tree.itemWidget(child, 2)
                        if combo:
                            combo.setCurrentIndex(0)
                    else:
                        line_spinbox = tree.itemWidget(child, 1)
                        if line_spinbox:
                            line_spinbox.setValue(1)
                        order_spinbox = tree.itemWidget(child, 2)
                        if order_spinbox:
                            order_spinbox.setValue(1)
            tree.blockSignals(False)

        self.treeWidget_menu.blockSignals(True)
        for i in range(self.treeWidget_menu.topLevelItemCount()):
            plugin_item = self.treeWidget_menu.topLevelItem(i)
            plugin_item.setCheckState(0, Qt.CheckState.Unchecked)
            for j in range(plugin_item.childCount()):
                plugin_item.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        self.treeWidget_menu.blockSignals(False)

        # Reset configuration checkboxes
        self.checkBox_icon.blockSignals(True)
        self.checkBox_icon.setChecked(False)
        self.checkBox_icon.blockSignals(False)

        self.checkBox_ajoutMenu.blockSignals(True)
        self.checkBox_ajoutMenu.setChecked(False)
        self.checkBox_ajoutMenu.blockSignals(False)

        self.checkBox_menuBar.blockSignals(True)
        self.checkBox_menuBar.setChecked(True)
        self.checkBox_menuBar.blockSignals(False)

        self._current_icon_path = ""
        self.pushButton_importIcon.setIcon(QIcon())
        self.pushButton_importIcon.setText("Choose icon")
        self.comboBox_emplacement.setEnabled(False)
        self.comboBox_emplacement.setCurrentIndex(0)
        self.pushButton_importIcon.setEnabled(False)
        self.treeWidget_menu.setEnabled(False)

    # ─────────────────────────────────────────────
    # BUTTON ACTIONS
    # ─────────────────────────────────────────────

    def _on_apply(self):
        """
        Preview the workspace currently shown in the editor.

        Builds the workspace dictionary from the live trees (so
        unsaved edits — visibility, area, line, order...) are
        included and delegates to :meth:`PerspectiveEngine.apply_preview`.
        This does **not** save anything: use :meth:`_on_save` for that.
        """
        item = self.listPerspectives.currentItem()
        if not item:
            QMessageBox.warning(
                self, "Warning", "Please select a workspace."
            )
            return

        name = self.inputName.text().strip() or item.text()
        data = self._build_data_from_tree(name)
        data["show_menu_bar"] = self.checkBox_menuBar.isChecked()
        self.engine.apply_preview(data)

    def _on_save(self):
        """
        Save the current workspace from the trees.

        Builds the dictionary via :meth:`_build_data_from_tree`,
        adds metadata (style, icon, menu bar, dropdown menus)
        and delegates to :meth:`PerspectiveEngine.save_from_data`.
        """
        new_name = self.inputName.text().strip()
        if not new_name:
            QMessageBox.warning(
                self, "Warning", "Please enter a name."
            )
            return

        # Get original name from the list
        current_item = self.listPerspectives.currentItem()
        if not current_item:
            QMessageBox.warning(
                self, "Warning",
                "Please select a workspace."
            )
            return

        old_name = current_item.text()

        # Case 1 — Name changed → rename first
        if new_name != old_name:
            if new_name in self.engine.list_perspectives():
                QMessageBox.warning(
                    self, "Name already exists",
                    f"A workspace named '{new_name}' already exists."
                )
                return
            self.engine.rename(old_name, new_name)

        # Case 2 — Save configuration
        data = self._build_data_from_tree(new_name)

        if self.checkBox_icon.isChecked():
            data["button_style"] = self.comboBox_emplacement.currentText()
            data["icon"]         = self._current_icon_path
        else:
            data["button_style"] = "text"
            data["icon"]         = ""

        data["show_menu_bar"] = self.checkBox_menuBar.isChecked()
        data["dropdown_menus"] = (
            self._get_selected_menus()
            if self.checkBox_ajoutMenu.isChecked()
            else []
        )

        self.engine.save_from_data(new_name, data)
        self._refresh_list()
        self.perspectiveSaved.emit()

        # Update selection in the list
        items = self.listPerspectives.findItems(
            new_name, Qt.MatchFlag.MatchExactly
        )
        if items:
            self.listPerspectives.blockSignals(True)
            self.listPerspectives.setCurrentItem(items[0])
            self.listPerspectives.blockSignals(False)

        QMessageBox.information(
            self, "Saved",
            f"Workspace '{new_name}' saved successfully ✓"
        )

    def _get_selected_menus(self) -> list:
        """
        Return the list of checked menus in ``treeWidget_menu``.

        Each element is a dictionary ``{"plugin": str, "menu": str}``.

        :return: List of selected menus.
        :rtype: list[dict]

        :example:

        .. code-block:: python

            menus = self._get_selected_menus()
            # → [
            #     {"plugin": "x", "menu": "study_menu"},
            #     {"plugin": "y",     "menu": "mesh_menu"},
            # ]
        """
        selected = []
        for i in range(self.treeWidget_menu.topLevelItemCount()):
            plugin_item = self.treeWidget_menu.topLevelItem(i)
            for j in range(plugin_item.childCount()):
                child = plugin_item.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    selected.append({
                        "plugin": child.data(1, Qt.ItemDataRole.UserRole),
                        "menu":   child.data(0, Qt.ItemDataRole.UserRole),
                    })
        return selected

    def _on_capture(self):
        """
        Capture the current QGIS interface state and save.

        Rescans plugins, captures the state via
        :class:`~perspective_manager.applicators.state_capture.StateCapture`
        and saves to ``self._cfg`` and ``user.psp.json``.
        """
        name = self.inputName.text().strip()
        if not name:
            QMessageBox.warning(
                self, "Warning",
                "Please select or create a workspace first."
            )
            return

        self.engine.registry      = self.engine.discovery.scan()
        self.engine.state_capture = StateCapture(self.engine.discovery)
        self.engine.save(name)
        self._load_perspective_in_tree(name)
        self._refresh_list()
        self.perspectiveSaved.emit()

        QMessageBox.information(
            self, "Captured",
            f"Workspace '{name}' updated from current QGIS state."
        )

    def _on_add(self):
        """
        Create a new workspace by capturing the current QGIS state.

        Asks the user for a name, checks for duplicates,
        creates the workspace via :meth:`PerspectiveEngine.add_perspective`
        and selects it in the list.
        """
        name, ok = QInputDialog.getText(
            self, "New workspace", "Workspace name:"
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        if name in self.engine.list_perspectives():
            QMessageBox.warning(
                self, "Name already exists",
                f"A workspace named '{name}' already exists."
            )
            return

        success = self.engine.add_perspective(name)
        if not success:
            QMessageBox.critical(
                self, "Error",
                "Unable to create the workspace."
            )
            return

        self._refresh_list()
        self.perspectiveSaved.emit()

        items = self.listPerspectives.findItems(
            name, Qt.MatchFlag.MatchExactly
        )
        if items:
            self.listPerspectives.setCurrentItem(items[0])

        self.inputName.setText(name)
        self._set_editor_visible(True)
        self._load_perspective_in_tree(name)

    def _on_duplicate(self):
        """
        Duplicate the selected workspace under a new name.

        Loads the original workspace, assigns the new name
        and saves it via :meth:`PerspectiveEngine.save_from_data`.
        """
        item = self.listPerspectives.currentItem()
        if not item:
            return

        old_name = item.text()
        new_name, ok = QInputDialog.getText(
            self, "Duplicate workspace", "New name:",
            text=f"{old_name} - copy"
        )
        if ok and new_name.strip():
            data         = self.engine.config_io.load(old_name)
            data["name"] = new_name.strip()
            self.engine.save_from_data(new_name.strip(), data)
            self._refresh_list()
            self.perspectiveSaved.emit()

    def _on_delete(self):
        """
        Delete the selected workspace after confirmation.

        Workspaces in :data:`PROTECTED_PERSPECTIVES` cannot
        be deleted.
        """
        item = self.listPerspectives.currentItem()
        if not item:
            return

        name = item.text()

        if name in PROTECTED_PERSPECTIVES:
            QMessageBox.warning(
                self, "Protected workspace",
                f"The workspace '{name}' cannot be deleted."
            )
            return

        reply = QMessageBox.question(
            self, "Delete workspace",
            f"Delete workspace '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.engine.delete(name)
            self.inputName.clear()
            self.listPerspectives.blockSignals(True)
            self.listPerspectives.clear()
            for n in self.engine.list_perspectives():
                self.listPerspectives.addItem(n)
            self.listPerspectives.blockSignals(False)
            self.perspectiveSaved.emit()
            self._reset_tree()
            self._set_editor_visible(False)

    # ─────────────────────────────────────────────
    # BUILD DICT FROM TREE
    # ─────────────────────────────────────────────

    def _build_data_from_tree(self, name: str) -> dict:
        """
        Build the workspace dictionary from the trees.

        Iterates through ``treeDocks`` and ``treeToolbars`` to extract
        each widget state (visibility, area, line, and — for
        toolbars — order within the line).

        The toolbar area is preserved from the existing JSON
        or from the registry if absent.

        :param name: Name of the workspace to build.
        :type name: str
        :return: Complete workspace dictionary.
        :rtype: dict
        """
        data         = {"name": name, "plugins": {}}
        registry     = self.engine.get_registry()
        plugin_names = list(registry.keys())

        # ── Read treeDocks ────────────────────────
        plugins_with_docks = [
            pn for pn in plugin_names if registry[pn].get("docks")
        ]
        for i in range(self.treeDocks.topLevelItemCount()):
            plugin_item = self.treeDocks.topLevelItem(i)
            plugin_name = plugins_with_docks[i]
            docks_cfg   = []

            for j in range(plugin_item.childCount()):
                child       = plugin_item.child(j)
                widget_name = child.data(0, Qt.ItemDataRole.UserRole)
                visible     = child.checkState(0) == Qt.CheckState.Checked
                combo       = self.treeDocks.itemWidget(child, 2)
                area        = combo.currentText() if combo else "left"

                docks_cfg.append({
                    "name":    widget_name,
                    "label":   child.text(0),
                    "visible": visible,
                    "area":    area,
                })

            if plugin_name not in data["plugins"]:
                data["plugins"][plugin_name] = {
                    "docks": [], "toolbars": []
                }
            data["plugins"][plugin_name]["docks"] = docks_cfg

        # ── Read treeToolbars ─────────────────────
        plugins_with_toolbars = [
            pn for pn in plugin_names if registry[pn].get("toolbars")
        ]
        for i in range(self.treeToolbars.topLevelItemCount()):
            plugin_item  = self.treeToolbars.topLevelItem(i)
            plugin_name  = plugins_with_toolbars[i]
            toolbars_cfg = []

            # Get areas from existing JSON
            existing = {
                t["name"]: t
                for t in self.engine.config_io.load(
                    self.inputName.text().strip()
                ).get("plugins", {}).get(plugin_name, {}).get(
                    "toolbars", []
                )
            }

            for j in range(plugin_item.childCount()):
                child         = plugin_item.child(j)
                widget_name   = child.data(0, Qt.ItemDataRole.UserRole)
                visible       = child.checkState(0) == Qt.CheckState.Checked
                line_spinbox  = self.treeToolbars.itemWidget(child, 1)
                line          = line_spinbox.value() if line_spinbox else 1
                order_spinbox = self.treeToolbars.itemWidget(child, 2)
                order         = order_spinbox.value() if order_spinbox else 1

                # Area from JSON or from registry
                existing_tb = existing.get(widget_name)
                if existing_tb:
                    area = existing_tb.get("area", "top")
                else:
                    reg_tbs = registry.get(plugin_name, {}).get(
                        "toolbars", []
                    )
                    reg_tb  = next(
                        (t for t in reg_tbs
                         if t["name"] == widget_name),
                        {}
                    )
                    area = reg_tb.get("area", "top")

                toolbars_cfg.append({
                    "name":    widget_name,
                    "label":   child.text(0),
                    "visible": visible,
                    "area":    area,
                    "line":    line,
                    "order":   order,
                })

            if plugin_name not in data["plugins"]:
                data["plugins"][plugin_name] = {
                    "docks": [], "toolbars": []
                }
            data["plugins"][plugin_name]["toolbars"] = toolbars_cfg

        return data

    # ─────────────────────────────────────────────
    # CENTRAL PANEL VISIBILITY
    # ─────────────────────────────────────────────

    def _set_editor_visible(self, visible: bool):
        """
        Show or hide the central editing panel.

        When ``visible`` is ``False``, shows ``labelPlaceholder``
        (invitation message to select a workspace).

        :param visible: ``True`` to show the panel, ``False``
            to show the placeholder.
        :type visible: bool
        """
        self.inputName.setVisible(visible)
        self.btnCapture.setVisible(visible)
        self.tabWidget.setVisible(visible)
        self.btnApply.setVisible(visible)
        self.btnSave.setVisible(visible)
        self.btnDuplicate.setVisible(visible)
        self.checkBox_menuBar.setVisible(visible)
        self.labelPlaceholder.setVisible(not visible)
        if hasattr(self, 'groupConfig'):
            self.groupConfig.setVisible(visible)