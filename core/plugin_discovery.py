# coding: utf-8

"""
Dynamic widget discovery module for QGIS plugins.

This module provides the :class:`PluginDiscovery` class, responsible for
scanning the QGIS interface and installed plugins to automatically detect
their :class:`QDockWidget`, :class:`QToolBar` and :class:`QMenu`.

**Detection strategies for third-party plugins:**

1. ``plugin.docks`` — list attribute of :class:`QDockWidget`.
2. ``plugin.toolbar`` — single :class:`QToolBar` attribute.
3. Inspection via ``dir()`` — iterates over all plugin attributes.

**Structure of the returned registry:**

.. code-block:: python

    {
        "__qgis_native__": {
            "display_name": "QGIS — native",
            "docks":    [{"name": "Layers", "label": "Layers", ...}],
            "toolbars": [{"name": "mMapNavToolBar", ...}],
            "menus":    [],
        },
        "georelai": {
            "display_name": "georelai",
            "docks":    [...],
            "toolbars": [...],
            "menus":    [{"name": "study_menu", "label": "Study", ...}],
        },
    }

:author: Adnan Benaboud — CNR
"""

from qgis.PyQt.QtWidgets import QDockWidget, QToolBar, QMenu
from qgis.PyQt.QtCore import Qt
from qgis.utils import plugins, iface


class PluginDiscovery:
    """
    Dynamic discovery of widgets (docks, toolbars, menus) from QGIS
    and installed plugins.

    The result is stored in :attr:`registry` after calling :meth:`scan`.

    :example:

    .. code-block:: python

        discovery = PluginDiscovery()
        registry  = discovery.scan()

        for plugin_name, plugin_data in registry.items():
            print(plugin_name, plugin_data["display_name"])
    """

    def __init__(self):
        """Initialize the instance with an empty registry."""
        self.registry = {}

    def scan(self) -> dict:
        """
        Run a full scan of the QGIS interface.

        Resets the registry, scans third-party plugins first,
        then native QGIS widgets.

        :return: Complete registry of discovered widgets.
        :rtype: dict

        :example:

        .. code-block:: python

            registry = discovery.scan()
            native   = registry["__qgis_native__"]
        """
        self.registry = {}
        self._scan_plugins()   # ← plugins first to claim their widgets
        self._scan_native()    # ← native excludes already claimed widgets
        return self.registry

    def _scan_native(self):
        """
        Scan native widgets from the QGIS main window.

        Detects all :class:`QDockWidget` and :class:`QToolBar`
        present in the main window and registers them under
        the ``__qgis_native__`` key.

        Excludes toolbars and docks already claimed by third-party
        plugins to avoid duplicates in the registry.
        """
        main_win        = iface.mainWindow()
        native_docks    = []
        native_toolbars = []

        # Collect IDs already claimed by plugins
        claimed_ids = set()
        for plugin_data in self.registry.values():
            for dock_info in plugin_data.get("docks", []):
                claimed_ids.add(id(dock_info["object"]))
            for tb_info in plugin_data.get("toolbars", []):
                claimed_ids.add(id(tb_info["object"]))

        # Scan native widgets excluding plugin widgets
        for dock in main_win.findChildren(QDockWidget):
            if id(dock) in claimed_ids:
                continue
            native_docks.append(self._describe_dock(dock))

        for toolbar in main_win.findChildren(QToolBar):
            if id(toolbar) in claimed_ids:
                continue
            native_toolbars.append(self._describe_toolbar(toolbar))

        if native_docks or native_toolbars:
            self.registry["__qgis_native__"] = {
                "display_name": "QGIS — native",
                "docks":        native_docks,
                "toolbars":     native_toolbars,
                "menus":        [],
            }

    def _scan_plugins(self):
        """
        Scan widgets from each installed QGIS plugin.

        For each plugin (excluding ``perspective_manager``), uses
        three successive strategies to detect widgets:

        1. **``docks`` attribute** — list of :class:`QDockWidget`.
        2. **``toolbar`` attribute** — single :class:`QToolBar` instance.
        3. **``dir()`` inspection** — iterates over all attributes
           if the first two strategies fail.

        Duplicates are avoided via name sets and memory identifiers.
        """
        claimed_docks    = set()
        claimed_toolbars = set()

        for plugin_name, plugin_instance in plugins.items():
            if plugin_name == "perspective_manager":
                continue

            plugin_docks    = []
            plugin_toolbars = []
            seen_dock_names = set()
            seen_tb_names   = set()

            # ── Strategy 1 — docks attribute ──────
            if hasattr(plugin_instance, 'docks'):
                try:
                    for dock in plugin_instance.docks:
                        if isinstance(dock, QDockWidget):
                            name = self._get_name(dock)
                            if name not in seen_dock_names:
                                seen_dock_names.add(name)
                                plugin_docks.append(
                                    self._describe_dock(dock)
                                )
                                claimed_docks.add(id(dock))
                except Exception:
                    pass

            # ── Strategy 2 — toolbar attribute ────
            if hasattr(plugin_instance, 'toolbar'):
                try:
                    tb = plugin_instance.toolbar
                    if isinstance(tb, QToolBar):
                        name = self._get_name(tb)
                        if name not in seen_tb_names:
                            seen_tb_names.add(name)
                            plugin_toolbars.append(
                                self._describe_toolbar(tb)
                            )
                            claimed_toolbars.add(id(tb))
                except Exception:
                    pass

            # ── Strategy 3 — dir() inspection ─────
            # Used only if the first two strategies fail
            if not plugin_docks and not plugin_toolbars:
                for attr_name in dir(plugin_instance):
                    if attr_name.startswith('__'):
                        continue
                    try:
                        attr = getattr(plugin_instance, attr_name)
                    except Exception:
                        continue

                    if isinstance(attr, QDockWidget) \
                            and id(attr) not in claimed_docks:
                        name = self._get_name(attr)
                        if name not in seen_dock_names:
                            seen_dock_names.add(name)
                            plugin_docks.append(
                                self._describe_dock(attr)
                            )
                            claimed_docks.add(id(attr))

                    elif isinstance(attr, QToolBar) \
                            and id(attr) not in claimed_toolbars:
                        name = self._get_name(attr)
                        if name not in seen_tb_names:
                            seen_tb_names.add(name)
                            plugin_toolbars.append(
                                self._describe_toolbar(attr)
                            )
                            claimed_toolbars.add(id(attr))

            # ── Scan menus ─────────────────────────
            plugin_menus = self._scan_plugin_menus(plugin_instance)

            if plugin_docks or plugin_toolbars or plugin_menus:
                self.registry[plugin_name] = {
                    "display_name": plugin_name,
                    "docks":        plugin_docks,
                    "toolbars":     plugin_toolbars,
                    "menus":        plugin_menus,
                }

    def _scan_plugin_menus(self, plugin_instance) -> list:
        """
        Discover :class:`QMenu` instances attached to a plugin.

        Inspects all plugin attributes looking for :class:`QMenu`
        instances. Duplicates are avoided via widget memory identifiers.

        :param plugin_instance: Plugin instance to inspect.
        :return: List of discovered menus, each as
            ``{"object": QMenu, "name": str, "label": str}``.
        :rtype: list[dict]
        """
        found_menus = []
        seen_ids    = set()

        for attr_name in dir(plugin_instance):
            if attr_name.startswith('__'):
                continue
            try:
                attr = getattr(plugin_instance, attr_name)
            except Exception:
                continue

            if isinstance(attr, QMenu) and id(attr) not in seen_ids:
                seen_ids.add(id(attr))
                found_menus.append({
                    "object": attr,
                    "name":   attr.objectName() or attr_name,
                    "label":  attr.title()       or attr_name,
                })

        return found_menus

    # ─────────────────────────────────────────────
    # WIDGET DESCRIPTION
    # ─────────────────────────────────────────────

    def _describe_dock(self, dock: QDockWidget) -> dict:
        """
        Build the description dictionary of a :class:`QDockWidget`.

        :param dock: Panel widget to describe.
        :type dock: QDockWidget
        :return: Dictionary with keys ``type``, ``object``, ``name``,
            ``label``, ``visible``, ``floating``, ``area``.
        :rtype: dict
        """
        main_win = iface.mainWindow()
        area     = main_win.dockWidgetArea(dock)
        return {
            "type":     "dock",
            "object":   dock,
            "name":     self._get_name(dock),
            "label":    dock.windowTitle() or self._get_name(dock),
            "visible":  dock.isVisible(),
            "floating": dock.isFloating(),
            "area":     self._area_to_str(area),
        }

    def _describe_toolbar(self, toolbar: QToolBar) -> dict:
        """
        Build the description dictionary of a :class:`QToolBar`.

        :param toolbar: Toolbar to describe.
        :type toolbar: QToolBar
        :return: Dictionary with keys ``type``, ``object``, ``name``,
            ``label``, ``visible``, ``floating``, ``area``.
        :rtype: dict
        """
        main_win = iface.mainWindow()
        area     = main_win.toolBarArea(toolbar)
        return {
            "type":     "toolbar",
            "object":   toolbar,
            "name":     self._get_name(toolbar),
            "label":    toolbar.windowTitle() or self._get_name(toolbar),
            "visible":  toolbar.isVisible(),
            "floating": toolbar.isFloating(),
            "area":     self._area_to_str(area),
        }

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def _get_name(self, widget) -> str:
        """
        Return the identifying name of a Qt widget.

        Priority: ``objectName()`` > normalized ``windowTitle()``
        > Python class name.

        :param widget: Qt widget to identify.
        :return: Widget name.
        :rtype: str
        """
        if widget.objectName():
            return widget.objectName()
        if widget.windowTitle():
            return widget.windowTitle().lower().replace(" ", "_")
        return widget.__class__.__name__

    def _area_to_str(self, area) -> str:
        """
        Convert a Qt dock/toolbar area constant to a string.

        :param area: Qt constant (e.g. ``Qt.LeftDockWidgetArea``).
        :return: String among ``"left"``, ``"right"``, ``"top"``,
            ``"bottom"``. Returns ``"left"`` by default.
        :rtype: str
        """
        mapping = {
            Qt.LeftDockWidgetArea:   "left",
            Qt.RightDockWidgetArea:  "right",
            Qt.TopDockWidgetArea:    "top",
            Qt.BottomDockWidgetArea: "bottom",
        }
        return mapping.get(area, "left")

    def str_to_area(self, area_str: str):
        """
        Convert an area string to a Qt constant.

        :param area_str: String among ``"left"``, ``"right"``,
            ``"top"``, ``"bottom"``.
        :type area_str: str
        :return: Corresponding Qt constant.
            Returns ``Qt.LeftDockWidgetArea`` by default.
        """
        mapping = {
            "left":   Qt.LeftDockWidgetArea,
            "right":  Qt.RightDockWidgetArea,
            "top":    Qt.TopDockWidgetArea,
            "bottom": Qt.BottomDockWidgetArea,
        }
        return mapping.get(area_str, Qt.LeftDockWidgetArea)


# ─────────────────────────────────────────────────
# UTILITY FUNCTION
# ─────────────────────────────────────────────────

def is_valid(widget) -> bool:
    """
    Check that a Qt widget is still valid in memory.

    Qt widgets can be destroyed on the C++ side while keeping
    their Python reference. This function detects this case by
    calling a simple method and catching :class:`RuntimeError`.

    :param widget: Qt widget to check.
    :return: ``True`` if the widget is valid,
        ``False`` if it has been destroyed.
    :rtype: bool

    :example:

    .. code-block:: python

        if is_valid(dock):
            dock.setVisible(True)
    """
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False