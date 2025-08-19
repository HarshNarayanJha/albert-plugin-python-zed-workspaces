# Copyright (c) 2025 Harsh Narayan Jha

"""
This plugin allows you to quickly open workspaces in Zed Editor

Disclaimer: This plugin is not officially affiliated with Zed or Zed Industries.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from sys import platform
from typing import override

from albert import (  # pyright: ignore[reportMissingModuleSource]
    Action,
    Item,
    Matcher,
    PluginInstance,
    Query,
    StandardItem,
    TriggerQueryHandler,
    runDetachedProcess,
)
from dateutil.parser import isoparse

md_iid = "3.0"
md_version = "1.0"
md_name = "Zed Workspaces"
md_description = "Open your Zed workspaces"
md_license = "MIT"
md_url = "https://github.com/HarshNarayanJha/albert_zed_workspaces"
md_lib_dependencies = ["python-dateutil"]
md_authors = ["@HarshNarayanJha"]


@dataclass
class Workspace:
    id: str
    name: str
    path: str
    last_opened: int


@dataclass
class Editor:
    name: str
    icon: str
    config_dir_prefix: str
    binary: str | None

    def __init__(self, name: str, icon: str, config_dir_prefix: str, binaries: list[str]):
        self.name = name
        self.icon = icon
        self.config_dir_prefix = config_dir_prefix
        self.binary = self._find_binary(binaries)

    def _find_binary(self, binaries: list[str]) -> str | None:
        for binary in binaries:
            if which(binary):
                return binary
        return None

    def list_workspaces(self) -> list[Workspace]:
        config_dir = Path.home() / ".local/share/"
        if platform == "darwin":
            config_dir = Path.home() / "Library" / "Application Support"

        dirs = list(config_dir.glob(f"{self.config_dir_prefix}*/"))
        if not dirs:
            return []
        latest = sorted(dirs)[-1]
        return self._parse_recent_workspaces(Path(latest) / "db.sqlite")

    def _parse_recent_workspaces(self, recent_workspaces_file: Path) -> list[Workspace]:
        try:
            workspaces: list[Workspace] = []
            with sqlite3.connect(recent_workspaces_file) as conn:
                cursor = conn.cursor()
                # NOTE: path might contain multiple paths, need to check
                cursor.execute("SELECT workspace_id, local_paths_array, timestamp FROM workspaces")
                for row in cursor:
                    if not row[1]:
                        continue

                    w_id = row[0]
                    local_path = row[1].strip()
                    timestamp = int(isoparse(row[2]).timestamp())

                    w_name = local_path.split("/")[-1]

                    workspaces.append(Workspace(id=w_id, name=w_name, path=local_path, last_opened=timestamp))

            return workspaces

        except FileNotFoundError:
            return []


class Plugin(PluginInstance, TriggerQueryHandler):
    def __init__(self):
        PluginInstance.__init__(self)
        TriggerQueryHandler.__init__(self)

        if platform == "darwin":
            zed_dir_name = "Zed"
            icon = "qfip:/Applications/Zed.app"
            icon_preview = "qfip:/Applications/Zed-Preview.app"
        elif platform == "linux":
            zed_dir_name = "zed"
            icon = "xdg:zed"
            icon_preview = "xdg:zed-preview"
        else:
            raise NotImplementedError(f"Unsupported platform: {platform}")

        editors = [
            Editor(
                name="Zed Editor",
                icon=icon,
                config_dir_prefix=f"{zed_dir_name}/db/0-stable",
                binaries=["zed", "zeditor", "zedit", "zed-cli"],
            ),
            Editor(
                name="Zed Editor (Preview)",
                icon=icon_preview,
                config_dir_prefix=f"{zed_dir_name}/db/0-preview",
                binaries=["zed", "zeditor", "zedit", "zed-cli"],
            ),
        ]
        self.editors: list[Editor] = [e for e in editors if e.binary is not None]

    @override
    def defaultTrigger(self) -> str:
        return "zd "

    @override
    def synopsis(self, query: str) -> str:
        return "<workspace name|path>"

    @override
    def handleTriggerQuery(self, query: Query):
        editor_workspace_pairs: list[tuple[Editor, Workspace]] = []

        m = Matcher(query.string)
        for editor in self.editors:
            workspaces = editor.list_workspaces()
            workspaces = [p for p in workspaces if Path(p.path).exists()]
            workspaces = [p for p in workspaces if m.match(p.name) or m.match(p.path)]
            editor_workspace_pairs.extend([(editor, p) for p in workspaces])

        # sort by last opened
        editor_workspace_pairs.sort(key=lambda pair: pair[1].last_opened, reverse=True)

        query.add([self._make_item(editor, workspace, query) for editor, workspace in editor_workspace_pairs])

    def _make_item(self, editor: Editor, workspace: Workspace, query: Query) -> Item:
        return StandardItem(
            id=str(workspace.id),
            text=workspace.name,
            subtext=workspace.path,
            inputActionText=query.trigger + workspace.name,
            iconUrls=[editor.icon],
            actions=[
                Action(
                    "Open",
                    "Open in %s" % editor.name,
                    lambda selected_workspace=workspace.path: runDetachedProcess(
                        # Binary has to be valid here
                        [editor.binary, selected_workspace]  # pyright: ignore[reportArgumentType]
                    ),
                )
            ],
        )

    @override
    def configWidget(self):
        return [
            {"type": "label", "text": str(__doc__).strip(), "widget_properties": {"textFormat": "Qt::MarkdownText"}},
        ]
