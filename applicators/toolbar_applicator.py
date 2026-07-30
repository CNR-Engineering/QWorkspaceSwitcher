# coding: utf-8

"""
Toolbar configuration applicator module.

This module provides the :class:`ToolbarApplicator` class, responsible for
positioning and displaying :class:`QToolBar` according to the
workspace configuration.

**Excluded toolbars** (never repositioned):

- ``QWorkspaceSwitcherToolbar`` — the plugin's own toolbar.
- ``QToolBar`` — widgets without a valid name.

**Linked toolbars** (managed automatically by their dock via Qt signal):

- ``mBrowserToolbar``
- ``mGpsToolBar``
- ``mBookmarkToolbar``
- ``processingToolbar``

**Line management:**

Toolbars are organized by area (``top``, ``bottom``, ``left``,
``right``) and by line number. An ``insertToolBarBreak`` is inserted
before the first toolbar of each line > 1.

:author: Adnan Benaboud — CNR
"""

from qgis.PyQt.QtWidgets import QToolBar
from qgis.PyQt.QtCore import Qt
from qgis.utils import iface

from ..core.plugin_discovery import is_valid


#: Toolbars never repositioned by the plugin.
EXCLUDED_TOOLBARS = {
    "QWorkspaceSwitcherToolbar",
    "QToolBar",
}

#: Toolbars linked to a dock — visibility follows the dock via Qt signal.
LINKED_TOOLBARS = {
    "mBrowserToolbar",
    "mGpsToolBar",
    "mBookmarkToolbar",
    "processingToolbar",
}


class ToolbarApplicator:
    """
    Apply toolbar configuration to the QGIS interface.

    Positions :class:`QToolBar` in the main window areas
    respecting the line order. The ``QWorkspaceSwitcherToolbar``
    is preserved at its current position on each application.

    :example:

    .. code-block:: python

        applicator = ToolbarApplicator(discovery)
        applicator.apply_all({
            "__qgis_native__": [
                {"name": "mMapNavToolBar", "visible": True,
                 "area": "top", "line": 1},
            ]
        })
    """

    #: String → Qt toolbar area constant mapping.
    AREA_MAP = {
        "top":    Qt.TopToolBarArea,
        "bottom": Qt.BottomToolBarArea,
        "left":   Qt.LeftToolBarArea,
        "right":  Qt.RightToolBarArea,
    }

    def __init__(self, discovery):
        """
        Initialize the applicator with the discovery registry.

        :param discovery: QGIS plugin discovery instance.
        :type discovery: PluginDiscovery
        """
        self.discovery = discovery

    def apply(self, plugin_name: str, toolbars_config: list):
        """
        Hide non-visible toolbars of a plugin.

        Does not reposition toolbars — used only to hide toolbars
        whose ``visible`` is ``False``.
        Ignores toolbars from :data:`EXCLUDED_TOOLBARS` and
        :data:`LINKED_TOOLBARS`.

        :param plugin_name: Name of the plugin owning the toolbars.
        :type plugin_name: str
        :param toolbars_config: List of toolbar configurations, each as
            ``{"name": str, "visible": bool, "area": str, "line": int}``.
        :type toolbars_config: list[dict]
        """
        for tb_cfg in toolbars_config:

            if tb_cfg["name"] in EXCLUDED_TOOLBARS:
                continue
            if tb_cfg["name"] in LINKED_TOOLBARS:
                continue

            toolbar = self._find(tb_cfg["name"])
            if toolbar is None or not is_valid(toolbar):
                continue

            if not tb_cfg.get("visible", True):
                toolbar.setVisible(False)

    def apply_all(self, all_toolbars_by_plugin: dict):
        """
        Reposition all visible toolbars according to area, line
        and in-line order.

        Performs in order:

        1. Save the position of ``QWorkspaceSwitcherToolbar``.
        2. Collect visible toolbars grouped by area and line.
        3. Remove all these toolbars from the main window.
        4. Replace them — sorted by ``order`` within each line —
           in the correct sequence, with line breaks between lines.
        5. Restore ``QWorkspaceSwitcherToolbar`` to its saved area,
           forcing it onto its own line if other toolbars share
           that area.

        Toolbars from :data:`EXCLUDED_TOOLBARS` and :data:`LINKED_TOOLBARS`
        are ignored.

        :param all_toolbars_by_plugin: Dictionary
            ``{plugin_name: [toolbar_config, ...]}``.
        :type all_toolbars_by_plugin: dict[str, list[dict]]

        :example:

        .. code-block:: python

            applicator.apply_all({
                "__qgis_native__": [
                    {"name": "mMapNavToolBar",   "visible": True,
                     "area": "top", "line": 1, "order": 1},
                    {"name": "mDigitizeToolBar", "visible": True,
                     "area": "top", "line": 1, "order": 2},
                ],
                "georelai": [
                    {"name": "GeorelaiToolbar",  "visible": True,
                     "area": "top", "line": 2, "order": 1},
                ]
            })
        """
        main_win   = iface.mainWindow()
        area_lines = {}

        # Collect visible toolbars grouped by area and line
        for plugin_name, toolbars_config in all_toolbars_by_plugin.items():
            for tb_cfg in toolbars_config:

                if tb_cfg["name"] in EXCLUDED_TOOLBARS:
                    continue
                if tb_cfg["name"] in LINKED_TOOLBARS:
                    continue
                if not tb_cfg.get("visible", True):
                    continue

                toolbar = self._find(tb_cfg["name"])
                if toolbar is None or not is_valid(toolbar):
                    continue

                area  = tb_cfg.get("area", "top")
                line  = tb_cfg.get("line", 1)
                order = tb_cfg.get("order", 1)

                if area not in area_lines:
                    area_lines[area] = {}
                if line not in area_lines[area]:
                    area_lines[area][line] = []

                area_lines[area][line].append({
                    "toolbar": toolbar,
                    "config":  tb_cfg,
                    "order":   order,
                })

        # Save position of QWorkspaceSwitcherToolbar
        pm_toolbar = None
        pm_area    = Qt.TopToolBarArea
        for tb in main_win.findChildren(QToolBar):
            if tb.objectName() == "QWorkspaceSwitcherToolbar":
                pm_toolbar = tb
                pm_area    = main_win.toolBarArea(tb)
                break

        # Remove all toolbars to be repositioned
        all_toolbars = set()
        for area_data in area_lines.values():
            for line_data in area_data.values():
                for entry in line_data:
                    all_toolbars.add(entry["toolbar"])

        # Clear stale line breaks left by toolbars we're not managing
        # in this call (e.g. LINKED_TOOLBARS, or any toolbar simply
        # absent from this workspace's config) but that still sit,
        # possibly hidden, in an area we're about to lay out. Left
        # alone, such a break would silently offset where "line 1"
        # actually starts, making line/order edits look like they
        # have no effect even though they were applied correctly.
        for area_str in area_lines:
            area = self.AREA_MAP.get(area_str, Qt.TopToolBarArea)
            for tb in main_win.findChildren(QToolBar):
                if tb in all_toolbars:
                    continue
                if main_win.toolBarArea(tb) != area:
                    continue
                if not is_valid(tb):
                    continue
                try:
                    main_win.removeToolBarBreak(tb)
                except Exception:
                    pass

        for tb in all_toolbars:
            if is_valid(tb):
                main_win.removeToolBar(tb)

        # Replace in correct order: by area, then by line, then by
        # the "order" field within each line. Ties (equal or missing
        # "order") fall back to the toolbar's objectName so the
        # result is deterministic instead of depending on dict
        # iteration order.
        for area_str, lines in area_lines.items():
            area = self.AREA_MAP.get(area_str, Qt.TopToolBarArea)
            for line_num in sorted(lines.keys()):
                toolbars_in_line = sorted(
                    lines[line_num],
                    key=lambda e: (e["order"], e["toolbar"].objectName())
                )
                for idx, entry in enumerate(toolbars_in_line):
                    toolbar = entry["toolbar"]
                    if not is_valid(toolbar):
                        continue
                    main_win.addToolBar(area, toolbar)
                    # Insert line break before first toolbar
                    # of each line > 1
                    if idx == 0 and line_num > 1:
                        main_win.insertToolBarBreak(toolbar)
                    toolbar.setVisible(True)

        # Restore QWorkspaceSwitcherToolbar to its saved position.
        # Force it onto its own line if anything was placed in the
        # same area — otherwise it would silently be appended right
        # after the last configured toolbar's line and merge into
        # it, instead of keeping the separate line it's always had.
        if pm_toolbar and is_valid(pm_toolbar):
            pm_area_has_others = any(
                self.AREA_MAP.get(area_str, Qt.TopToolBarArea) == pm_area
                for area_str in area_lines
            )
            main_win.addToolBar(pm_area, pm_toolbar)
            if pm_area_has_others:
                main_win.insertToolBarBreak(pm_toolbar)
            pm_toolbar.setVisible(True)

    def _find(self, name: str):
        """
        Search for a :class:`QToolBar` by name in the registry.

        :param name: Name (``objectName``) of the toolbar to find.
        :type name: str
        :return: Toolbar instance, or ``None`` if not found.
        :rtype: QToolBar or None
        """
        for plugin_data in self.discovery.registry.values():
            for tb_info in plugin_data.get("toolbars", []):
                if tb_info["name"] == name:
                    return tb_info["object"]
        return None