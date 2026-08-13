# QWorkspace Switcher — QGIS Plugin

![QGIS](https://img.shields.io/badge/QGIS-3.x%20%7C%204.x-green)
![License](https://img.shields.io/badge/license-BSD--2--Clause-blue)
![Version](https://img.shields.io/badge/version-1.0.0-orange)
![Python](https://img.shields.io/badge/python-3.x-yellow)
[![QGIS Plugin Repository](https://img.shields.io/badge/QGIS%20Plugin%20Repository-QWorkspaceSwitcher-589632)](https://plugins.qgis.org/plugins/QWorkspaceSwitcher/)

A QGIS plugin to create, manage and apply named interface
configurations called **workspaces**. Switch between different
working environments in one click.

---

## Table of Contents

- [Why QWorkspace Switcher?](#why-qworkspace-switcher)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Plugin Integration](#plugin-integration)
- [Configuration File](#configuration-file)
- [Architecture](#architecture)
- [License](#license)
- [Author](#author)
- [Contributing](#contributing)
- [Related Projects](#related-projects)

---

## Why QWorkspace Switcher?

QGIS is a powerful GIS platform, but its interface can be
overwhelming — especially for users who switch between different
tasks during the same working session (data collection,
hydraulic modeling, results analysis...).

The native QGIS customization options (profiles, manual toolbar
toggling) are insufficient for fast context switching:
- **Changing a profile** requires restarting QGIS entirely
- **Manual reorganization** is repetitive and time-consuming
- **No named configurations** can be saved and reapplied

**QWorkspace Switcher** solves this by letting you define
dedicated interface configurations for each workflow and
switch between them instantly from the toolbar.

Originally developed at CNR (Compagnie Nationale du Rhône)
for hydraulic modeling workflows, QWorkspace Switcher is
designed as a **generic, domain-independent tool** for any
QGIS user or organization.

---

## Features

- **Create workspaces** by capturing the current QGIS
  interface state in one click
- **Apply a workspace** instantly from the toolbar button
- **Configure each button** style:
  - `text` — text only
  - `icon` — icon only
  - `icon_text` — icon on the left + text
  - `text_icon` — text on the left + icon on the right
- **Custom icon** per workspace (PNG, SVG, JPG, ICO)
- **Dropdown menu** per workspace — quick access to plugin menus
- **Show/hide the QGIS menu bar** per workspace for a
  clean application-like experience
- **Declarative `.psp.json` system** — third-party plugins
  can declare their own recommended workspaces
- **Blacklist system** — deleted plugin workspaces stay
  deleted across sessions
- **Export/import** workspace configuration file
- **Emergency shortcut** `Ctrl+Shift+M` to restore the
  QGIS menu bar at any time

---

## Installation

### From the QGIS Plugin Manager (recommended)

```
Plugins → Manage and Install Plugins →
Search "QWorkspace Switcher" → Install
```

Also listed on the
[official QGIS Plugin Repository](https://plugins.qgis.org/plugins/QWorkspaceSwitcher/).

### Manual installation

1. Download the latest release from
   [GitHub Releases](https://github.com/AdnanBenaboud/QWorkspaceSwitcher/releases)
2. Extract to your QGIS plugins folder:
   - **Windows:**
     `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - **Linux:**
     `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **macOS:**
     `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS
4. Enable the plugin:
   `Plugins → Manage and Install Plugins → Installed`

### Requirements

- QGIS 3.0 or later (including QGIS 4.x / PyQt6)
- Python 3.x
- PyQt5 (included with QGIS)

---

## Usage

### Creating a workspace

1. Configure your QGIS interface manually
   (show/hide panels and toolbars as desired)
2. Click the **⚙** button in the QWorkspace Switcher toolbar
3. Click **+** to create a new workspace
4. The current interface state is captured automatically
5. Configure the button style and icon if needed
6. Click **Save**

### Applying a workspace

Click the workspace button in the toolbar — the interface
switches instantly. The active workspace button appears pressed.

### Editing a workspace

1. Open the management window (⚙ button)
2. Select the workspace in the list
3. Modify panels, toolbars and menus via the three tabs:
   - **Panels** — select and position `QDockWidget`
   - **Toolbars** — select and organize `QToolBar` by line and,
     within a line, by left-to-right order
   - **Menus** — select plugin menus for the dropdown button
4. Click **Save**

### Renaming a workspace

1. Select the workspace in the list
2. Edit the name in the name field
3. Click **Save** — the workspace is renamed automatically

### Duplicating a workspace

Select a workspace and click **Duplicate** to create a copy
under a new name.

### Exporting workspaces

Click **Export** to save `user.psp.json` to a chosen location.
This file can be shared between team members to standardize
working environments.

### Emergency shortcut

If the QGIS menu bar is hidden by a workspace, press
**Ctrl+Shift+M** to restore it at any time.

---

## Plugin Integration

QWorkspace Switcher is designed to work seamlessly with
third-party plugins. There are two levels of integration.

### Level 1 — Automatic detection (no code change required)

QWorkspace Switcher automatically detects your plugin's
widgets using three successive strategies:

| Strategy | What it looks for | Reliability |
|---|---|---|
| 1 | `self.docks` attribute | ✅ High |
| 2 | `self.toolbar` attribute | ✅ High |
| 3 | `dir()` inspection | ⚠️ Medium |

> **Strategies 1 and 2 are strongly recommended** for
> reliable and predictable detection.

### Level 2 — Full integration (recommended)

#### Step 1 — Declare widgets in `initGui()`

Expose your widgets as attributes of your plugin's main class.

> ⚠️ **Critical:** Widgets **must** be declared in `__init__()`
> or `initGui()` — **not** in `run()` — to be detected at
> QGIS startup.

```python
class MyPlugin:
    def initGui(self):

        # ── Expose docks (Strategy 1) ──────────────
        self.dock_import  = MyImportDock(self.iface.mainWindow())
        self.dock_results = MyResultsDock(self.iface.mainWindow())

        # List ALL docks in self.docks
        self.docks = [
            self.dock_import,
            self.dock_results,
        ]

        self.iface.addDockWidget(
            Qt.RightDockWidgetArea, self.dock_import
        )
        self.iface.addDockWidget(
            Qt.LeftDockWidgetArea, self.dock_results
        )

        # ── Expose toolbar (Strategy 2) ─────────────
        self.toolbar = QToolBar("My Plugin")
        self.toolbar.setObjectName("MyPluginToolbar")
        self.iface.addToolBar(self.toolbar)

        # ── Expose menus (optional) ──────────────────
        self.analysis_menu = QMenu("Analysis")
        self.analysis_menu.setObjectName("analysis_menu")
        self.iface.mainWindow().menuBar().addMenu(
            self.analysis_menu
        )
```

> ⚠️ **Important:** Every widget must have a **unique and
> stable** `objectName`. Changing an `objectName` between
> plugin versions will break existing user workspaces.

#### Step 2 — Create a `.psp.json` declaration file

Create a file named `<your_plugin_name>.psp.json` at the
**root of your plugin folder**. This file declares the
recommended workspaces for your plugin's users.

These workspaces are loaded automatically at QGIS startup
and appear in the QWorkspace Switcher toolbar.

```json
{
  "perspectives": [
    {
      "name": "Data collection",
      "button_style": "text",
      "icon": "",
      "show_menu_bar": true,
      "dropdown_menus": [
        {"plugin": "myplugin", "menu": "analysis_menu"}
      ],
      "plugins": {
        "myplugin": {
          "docks": [
            {
              "name":    "my_import_dock",
              "label":   "Import",
              "visible": true,
              "area":    "right"
            },
            {
              "name":    "my_results_dock",
              "label":   "Results",
              "visible": false,
              "area":    "left"
            }
          ],
          "toolbars": [
            {
              "name":    "MyPluginToolbar",
              "label":   "My Plugin",
              "visible": true,
              "area":    "top",
              "line":    2,
              "order":   1
            }
          ]
        },
        "__qgis_native__": {
          "docks": [
            {
              "name":    "Layers",
              "label":   "Layers",
              "visible": true,
              "area":    "left"
            }
          ],
          "toolbars": [
            {
              "name":    "mMapNavToolBar",
              "label":   "Map Navigation",
              "visible": true,
              "area":    "top",
              "line":    1,
              "order":   1
            }
          ]
        }
      }
    },
    {
      "name": "Results analysis",
      "button_style": "text",
      "icon": "",
      "show_menu_bar": true,
      "dropdown_menus": [],
      "plugins": {
        "myplugin": {
          "docks": [
            {
              "name":    "my_import_dock",
              "label":   "Import",
              "visible": false,
              "area":    "right"
            },
            {
              "name":    "my_results_dock",
              "label":   "Results",
              "visible": true,
              "area":    "right"
            }
          ],
          "toolbars": [
            {
              "name":    "MyPluginToolbar",
              "label":   "My Plugin",
              "visible": true,
              "area":    "top",
              "line":    2,
              "order":   1
            }
          ]
        }
      }
    }
  ]
}
```

### `.psp.json` field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✅ | Unique workspace name |
| `button_style` | string | ✅ | `text`, `icon`, `icon_text`, `text_icon` |
| `icon` | string | ❌ | Path to button icon file |
| `show_menu_bar` | bool | ❌ | Show QGIS menu bar (default: `true`) |
| `window_state` | string | ❌ | Base64 `QMainWindow.saveState()` blob, captured automatically. Opaque — restored as a geometry baseline (splitters, floating geometry, tab order) before `plugins` is applied, never overrides it. Not meant to be hand-written. |
| `dropdown_menus` | list | ❌ | Menus to show in button dropdown |
| `dropdown_menus[].plugin` | string | ✅ | Plugin name |
| `dropdown_menus[].menu` | string | ✅ | Menu `objectName` |
| `plugins` | dict | ✅ | Widget config per plugin |
| `docks[].name` | string | ✅ | `objectName` of `QDockWidget` |
| `docks[].label` | string | ✅ | Display label |
| `docks[].visible` | bool | ✅ | Visibility in this workspace |
| `docks[].area` | string | ✅ | `left`, `right`, `top`, `bottom` |
| `toolbars[].name` | string | ✅ | `objectName` of `QToolBar` |
| `toolbars[].label` | string | ✅ | Display label |
| `toolbars[].visible` | bool | ✅ | Visibility in this workspace |
| `toolbars[].area` | string | ✅ | `top`, `bottom`, `left`, `right` |
| `toolbars[].line` | int | ✅ | Line number in area (1 = first line; the UI caps this dynamically at one more than the highest line already in use in that area) |
| `toolbars[].order` | int | ❌ | Position within the line, left/top to right/bottom — `0` = unordered/first (default: `1`) |

### Priority and merge rules

When multiple `.psp.json` files are found, workspaces are
merged according to the following priority:
  
```
CONFIG_DEFAULT          (lowest priority)
    ↓
plugin_a.psp.json
    ↓
plugin_b.psp.json
    ↓
user.psp.json           (highest priority)
    ↓
self._cfg               (merged in memory)
```

- **Same name in user and plugin** → user version wins
- **User deletes a plugin workspace** → added to
  `deleted_perspectives` blacklist → stays deleted
  across sessions even after plugin updates

### Integration checklist

```
In your Python code (initGui):
  ✅ self.docks = [...] declared
  ✅ self.toolbar with unique stable objectName
  ✅ QMenu attributes with unique stable objectName
  ✅ All widgets declared in initGui(), NOT in run()

In your plugin folder:
  ✅ <plugin_name>.psp.json created at root folder
  ✅ objectNames match between code and JSON
  ✅ Tested in QGIS with QWorkspace Switcher installed
  ✅ Workspaces documented in your plugin README
```

---

## Configuration File

User workspaces are stored in:

```
<qworkspace_switcher_dir>/perspectives/user.psp.json
```

This file can be shared between team members to standardize
working environments across a project. The file includes:

- `perspectives` — list of user workspaces
- `deleted_perspectives` — blacklist of deleted plugin workspaces

```json
{
  "perspectives": [
    {
      "name": "QGIS",
      "button_style": "text",
      "show_menu_bar": true,
      "plugins": { ... }
    }
  ],
  "deleted_perspectives": ["Modeling"]
}
```

---

## Architecture

QWorkspace Switcher follows a layered architecture:

```
┌──────────────────────────────────────────┐
│           Presentation Layer             │
│  MainWindow (Qt Designer)                │
│  PerspectiveManager (toolbar)            │
└──────────────┬───────────────────────────┘
               │
┌──────────────▼───────────────────────────┐
│            Business Layer                │
│          PerspectiveEngine               │
└───┬──────────────┬──────────────┬────────┘
    │              │              │
┌───▼───────┐ ┌────▼──────┐ ┌────▼──────────┐
│PluginDisc.│ │ ConfigIO  │ │  Applicators  │
│           │ │           │ │ DockApplicator│
│ Dynamic   │ │ Single    │ │ToolbarApplica.│
│ discovery │ │ source of │ │ StateCapture  │
│ of widgets│ │ truth     │ │               │
└───────────┘ └────┬──────┘ └───────────────┘
                   │
            ┌──────▼──────┐
            │user.psp.json│
            │*.psp.json   │
            └─────────────┘
```

**Key design decisions:**
- `self._cfg` is the **single source of truth** — all
  operations go through memory, no file reads during session
- Plugin scan order: **third-party plugins first**, then
  native QGIS — prevents widget duplication in registry
- `QFileSystemWatcher` detects external file changes with
  `_writing` flag + `QTimer` to prevent infinite loops

---

## License

BSD-2-Clause — see [LICENSE](LICENSE) file

---

## Author

**Adnan Benaboud**
CNR — Compagnie Nationale du Rhône
[GitHub](https://github.com/AdnanBenaboud)

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch:
   `git checkout -b feature/my-feature`
3. Commit your changes:
   `git commit -m "feat: add my feature"`
4. Push to the branch:
   `git push origin feature/my-feature`
5. Open a Pull Request

### Reporting issues

Please use the
[GitHub issue tracker](https://github.com/CNR-Engineering/QWorkspaceSwitcher/issues)
to report bugs or request features.

---

## Related Projects

- [QGIST Workbench](https://github.com/programmer-punk/workbench)
  — Similar concept without declarative plugin integration system
- [QGIS Profiles](https://docs.qgis.org/latest/en/docs/user_manual/introduction/qgis_configuration.html#working-with-user-profiles)
  — Native QGIS user profiles (requires restart to switch)
