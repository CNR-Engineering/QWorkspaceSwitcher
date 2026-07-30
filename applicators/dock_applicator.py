# coding: utf-8

"""
Dock panel configuration applicator module.

This module provides the :class:`DockApplicator` class, responsible for
positioning and displaying :class:`QDockWidget` according to the
workspace configuration.

**Placement strategies based on the number of docks per area:**

.. code-block:: text

    1 dock  → normal placement (addDockWidget)
    2 docks → side by side or vertical split (splitDockWidget)
    3 docks → tabbed layout (tabifyDockWidget)

:author: Adnan Benaboud — CNR
"""

from qgis.PyQt.QtWidgets import QDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.utils import iface

from ..core.plugin_discovery import is_valid


class DockApplicator:
    """
    Apply dock panel configuration to the QGIS interface.

    Positions :class:`QDockWidget` in the main window areas
    according to the active workspace configuration.

    The placement strategy depends on the number of visible docks
    in each area:

    - **1 dock** → normal placement via ``addDockWidget``.
    - **2 docks** → split via ``splitDockWidget``.
    - **3 docks or more** → tabbed layout via ``tabifyDockWidget``.

    :example:

    .. code-block:: python

        applicator = DockApplicator(discovery)
        applicator.apply("georelai", docks_config)
    """

    def __init__(self, discovery):
        """
        Initialize the applicator with the discovery registry.

        :param discovery: QGIS plugin discovery instance.
        :type discovery: PluginDiscovery
        """
        self.discovery = discovery

    def apply(self, plugin_name: str, docks_config: list):
        """
        Apply the dock configuration for a plugin.

        For each dock in the configuration:

        - Hides the dock if ``visible`` is ``False``.
        - Groups visible docks by area.
        - Applies the appropriate placement strategy.

        :param plugin_name: Name of the plugin owning the docks.
        :type plugin_name: str
        :param docks_config: List of dock configurations, each as
            ``{"name": str, "visible": bool, "area": str}``.
        :type docks_config: list[dict]

        :example:

        .. code-block:: python

            applicator.apply("georelai", [
                {"name": "import_bornes",
                 "visible": True,  "area": "right"},
                {"name": "edition_profil",
                 "visible": False, "area": "left"},
            ])
        """
        main_win    = iface.mainWindow()
        area_groups = {}

        for dock_cfg in docks_config:
            dock = self._find(dock_cfg["name"])

            if dock is None or not is_valid(dock):
                continue

            # Hide non-visible docks
            if not dock_cfg.get("visible", True):
                dock.setVisible(False)
                continue

            # Group visible docks by area
            area = dock_cfg.get("area", "left")
            if area not in area_groups:
                area_groups[area] = []
            area_groups[area].append({
                "dock":   dock,
                "config": dock_cfg,
            })

        # Apply placement strategy based on number of docks per area
        for area_str, group in area_groups.items():
            area = self.discovery.str_to_area(area_str)

            if len(group) == 1:
                self._apply_single(main_win, area, group[0]["dock"])
            elif len(group) == 2:
                self._apply_split(main_win, area, group)
            else:
                self._apply_tabified(main_win, area, group)

    # ─────────────────────────────────────────────
    # PLACEMENT STRATEGIES
    # ─────────────────────────────────────────────

    def _apply_single(self, main_win, area, dock: QDockWidget):
        """
        Place a single dock in an area.

        Re-anchors the dock if it is floating before placing it.

        :param main_win: QGIS main window.
        :param area: Qt area constant (e.g. ``Qt.LeftDockWidgetArea``).
        :param dock: Dock to place.
        :type dock: QDockWidget
        """
        if not is_valid(dock):
            return

        if dock.isFloating():
            dock.setFloating(False)

        main_win.addDockWidget(area, dock)
        dock.setVisible(True)

    def _apply_split(self, main_win, area, group: list):
        """
        Place two docks side by side or one above the other.

        Uses ``splitDockWidget`` to share space between the two docks.
        The split orientation depends on the area:

        - Left/right area → **vertical** split (one above the other).
        - Top/bottom area → **horizontal** split (side by side).

        :param main_win: QGIS main window.
        :param area: Qt area constant.
        :param group: List of two entries ``{"dock": QDockWidget, ...}``.
        :type group: list[dict]
        """
        dock1 = group[0]["dock"]
        dock2 = group[1]["dock"]

        if not is_valid(dock1) or not is_valid(dock2):
            return

        if dock1.isFloating():
            dock1.setFloating(False)
        if dock2.isFloating():
            dock2.setFloating(False)

        main_win.addDockWidget(area, dock1)
        dock1.setVisible(True)

        # Split orientation based on area
        if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
            main_win.splitDockWidget(dock1, dock2, Qt.Vertical)
        else:
            main_win.splitDockWidget(dock1, dock2, Qt.Horizontal)

        dock2.setVisible(True)

    def _apply_tabified(self, main_win, area, group: list):
        """
        Place three or more docks as tabs in the same area.

        The first dock is placed normally. The following ones are
        tabified onto the first via ``tabifyDockWidget``.
        The first dock is brought to the foreground after tabification.

        :param main_win: QGIS main window.
        :param area: Qt area constant.
        :param group: List of at least three entries
            ``{"dock": QDockWidget, ...}``.
        :type group: list[dict]
        """
        first_dock = group[0]["dock"]
        if not is_valid(first_dock):
            return

        if first_dock.isFloating():
            first_dock.setFloating(False)

        main_win.addDockWidget(area, first_dock)
        first_dock.setVisible(True)

        # Tabify following docks onto the first
        for entry in group[1:]:
            dock = entry["dock"]
            if not is_valid(dock):
                continue
            if dock.isFloating():
                dock.setFloating(False)
            main_win.tabifyDockWidget(first_dock, dock)
            dock.setVisible(True)

        # Bring first dock to the foreground
        first_dock.raise_()

    # ─────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────────

    def _find(self, name: str):
        """
        Search for a :class:`QDockWidget` by name in the registry.

        :param name: Name (``objectName``) of the dock to find.
        :type name: str
        :return: Dock instance, or ``None`` if not found.
        :rtype: QDockWidget or None
        """
        for plugin_data in self.discovery.registry.values():
            for dock_info in plugin_data.get("docks", []):
                if dock_info["name"] == name:
                    return dock_info["object"]
        return None