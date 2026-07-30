# coding: utf-8

"""
Current QGIS interface state capture module.

This module provides the :class:`StateCapture` class, responsible for
capturing the visible state of all docks and toolbars in the QGIS
interface at a given moment, in order to save it as a workspace.

**Toolbars excluded from capture:**

- ``QToolBar`` — widgets without a valid name.
- ``mBrowserToolbar`` — linked to the Browser dock (managed by Qt signal).
- ``mGpsToolBar`` — linked to the GPS dock.
- ``mBookmarkToolbar`` — linked to the Bookmarks dock.
- ``processingToolbar`` — linked to the Processing dock.

:author: Adnan Benaboud — CNR
"""

from qgis.PyQt.QtWidgets import QToolBar
from qgis.PyQt.QtCore import Qt
from qgis.utils import iface

from ..core.plugin_discovery import is_valid


class StateCapture:
    """
    Capture the current state of the QGIS interface.

    Iterates over the plugin registry provided by
    :class:`~perspective_manager.core.plugin_discovery.PluginDiscovery`
    and records for each dock and toolbar: its visibility, area,
    and — for toolbars — its line and order within that line.

    :example:

    .. code-block:: python

        discovery = PluginDiscovery()
        discovery.scan()
        capture   = StateCapture(discovery)
        data      = capture.capture("Field survey")
    """

    #: Toolbars excluded from capture — linked to a dock or without valid name.
    EXCLUDED_TOOLBARS = [
        "QToolBar",
        "mBrowserToolbar",
        "mGpsToolBar",
        "mBookmarkToolbar",
        "processingToolbar",
    ]

    def __init__(self, discovery):
        """
        Initialize the instance with the discovery registry.

        :param discovery: QGIS plugin discovery instance.
        :type discovery: PluginDiscovery
        """
        self.discovery = discovery

    def capture(self, name: str) -> dict:
        """
        Capture the current state of all docks and toolbars.

        Iterates over :attr:`PluginDiscovery.registry` and
        records for each plugin:

        - The state of its docks (visibility, area).
        - The state of its toolbars (visibility, area, line).

        Duplicates and invalid widgets are ignored.
        Toolbars in :attr:`EXCLUDED_TOOLBARS` are excluded.

        :param name: Name of the workspace to create.
        :type name: str
        :return: Captured workspace dictionary.
        :rtype: dict

        :example:

        .. code-block:: python

            data = capture.capture("Field survey")
            # → {
            #     "name": "Field survey",
            #     "plugins": {
            #         "__qgis_native__": {
            #             "docks": [
            #                 {"name": "Layers",
            #                  "visible": True, ...}
            #             ],
            #             "toolbars": [
            #                 {"name": "mMapNavToolBar",
            #                  "line": 1, ...}
            #             ]
            #         },
            #         "georelai": {...}
            #     }
            # }
        """
        main_win = iface.mainWindow()
        data     = {"name": name, "plugins": {}}

        for plugin_name, plugin_data in self.discovery.registry.items():
            docks_state     = []
            toolbars_state  = []
            seen_dock_names = set()
            seen_tb_names   = set()

            # ── Capture docks ─────────────────────
            for dock_info in plugin_data.get("docks", []):
                dock = dock_info["object"]

                if not is_valid(dock):
                    continue
                if dock_info["name"] in seen_dock_names:
                    continue

                seen_dock_names.add(dock_info["name"])
                area = main_win.dockWidgetArea(dock)

                docks_state.append({
                    "name":    dock_info["name"],
                    "label":   dock_info["label"],
                    "visible": dock.isVisible(),
                    "area":    self.discovery._area_to_str(area),
                })

            # ── Capture toolbars ──────────────────
            for tb_info in plugin_data.get("toolbars", []):
                tb = tb_info["object"]

                if not is_valid(tb):
                    continue
                if tb_info["name"] in self.EXCLUDED_TOOLBARS:
                    continue
                if tb_info["name"] in seen_tb_names:
                    continue

                seen_tb_names.add(tb_info["name"])
                area     = main_win.toolBarArea(tb)
                area_str = self.discovery._area_to_str(area)
                line, order = self._detect_line_and_order(
                    main_win, tb, area_str
                )

                toolbars_state.append({
                    "name":    tb_info["name"],
                    "label":   tb_info["label"],
                    "visible": tb.isVisible(),
                    "area":    area_str,
                    "line":    line,
                    "order":   order,
                })

            if docks_state or toolbars_state:
                data["plugins"][plugin_name] = {
                    "docks":    docks_state,
                    "toolbars": toolbars_state,
                }

        return data

    def _detect_line_and_order(self, main_win, toolbar: QToolBar,
                               area_str: str) -> tuple:
        """
        Detect the line number and within-line order of a toolbar.

        Line boundaries are read from Qt's own
        ``QMainWindow.toolBarBreak()`` state rather than inferred by
        comparing raw pixel positions: two toolbars can legitimately
        share the same coordinate (or report ``(0, 0)`` if the main
        window hasn't been laid out yet), which made the previous
        pixel-only comparison occasionally collapse distinct lines
        into one. ``toolBarBreak()`` is unaffected by that — it is a
        layout property, not a paint-time one.

        Toolbars are still ordered by geometry first (reading order:
        top-to-bottom then left-to-right for ``top``/``bottom``
        areas, left-to-right then top-to-bottom for ``left``/
        ``right``) — Qt exposes no public API for the exact sequence
        of toolbars within an area, so this remains the best
        available proxy for traversal order. The line number itself,
        though, comes from the break flags encountered while walking
        that order, not from the coordinates.

        :param main_win: QGIS main window.
        :param toolbar: Toolbar whose position to find.
        :type toolbar: QToolBar
        :param area_str: Toolbar area (``"top"``, ``"bottom"``,
            ``"left"``, ``"right"``).
        :type area_str: str
        :return: ``(line, order)``, both starting at ``1``.
            Returns ``(1, 1)`` if the toolbar isn't found in its
            own area (shouldn't happen in practice).
        :rtype: tuple[int, int]

        :example:

        .. code-block:: python

            line, order = capture._detect_line_and_order(
                main_win, toolbar, "top"
            )
            # → (2, 1)  first toolbar on the second line
        """
        area_map = {
            "top":    Qt.TopToolBarArea,
            "bottom": Qt.BottomToolBarArea,
            "left":   Qt.LeftToolBarArea,
            "right":  Qt.RightToolBarArea,
        }
        area = area_map.get(area_str, Qt.TopToolBarArea)

        # Visible toolbars in the same area, in reading order
        same_area = [
            tb for tb in main_win.findChildren(QToolBar)
            if main_win.toolBarArea(tb) == area and tb.isVisible()
        ]
        if area_str in ("top", "bottom"):
            same_area.sort(key=lambda t: (t.geometry().y(), t.geometry().x()))
        else:
            same_area.sort(key=lambda t: (t.geometry().x(), t.geometry().y()))

        line          = 1
        order_in_line = 0

        for idx, tb in enumerate(same_area):
            # A break before the very first toolbar of the area
            # doesn't start a new line — there's nothing before it.
            if idx > 0 and main_win.toolBarBreak(tb):
                line += 1
                order_in_line = 0
            order_in_line += 1

            if tb is toolbar:
                return line, order_in_line

        return 1, 1