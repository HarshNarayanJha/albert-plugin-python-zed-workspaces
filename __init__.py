# Copyright (c) 2026 Harsh Narayan Jha

"""
This plugin allows you to quickly open workspaces in Zed Editor

Disclaimer: This plugin is not officially affiliated with Zed or Zed Industries.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from sys import platform
from typing import Generator, cast, override

from dateutil.parser import isoparse  # ty:ignore[unresolved-import]

from albert import (
    Action,
    GeneratorQueryHandler,
    Icon,
    Item,
    MatchConfig,
    Matcher,
    PluginInstance,
    QueryContext,
    StandardItem,
    openFile,
    runDetachedProcess,
    runTerminal,
)

md_iid = "5.0"
md_version = "3.0"
md_name = "Zed Workspaces"
md_description = "Open your Zed workspaces"
md_license = "MIT"
md_url = "https://github.com/HarshNarayanJha/albert-plugin-python-zed-workspaces"
md_readme_url = "https://github.com/HarshNarayanJha/albert-plugin-python-zed-workspaces/blob/main/README.md"
md_lib_dependencies = ["python-dateutil"]
md_authors = ["@HarshNarayanJha"]
md_maintainers = ["@HarshNarayanJha"]


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

        dirs = list(config_dir.glob(f"{self.config_dir_prefix}/"))
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
                cursor.execute("SELECT workspace_id, paths, timestamp FROM workspaces")
                for row in cursor:
                    if not row[1]:
                        continue

                    w_id = row[0]
                    local_path = row[1].strip()
                    timestamp = int(isoparse(row[2]).timestamp())

                    w_name = local_path.split("/")[-1]

                    workspaces.append(Workspace(id=w_id, name=w_name, path=local_path, last_opened=timestamp))

            return workspaces

        except sqlite3.OperationalError:
            warning(f"Please update your Zed to the latest version for {recent_workspaces_file}")  # ty:ignore[unresolved-reference]  # noqa: F821
            return []

        except FileNotFoundError:
            return []


class Plugin(PluginInstance, GeneratorQueryHandler):
    def __init__(self):
        PluginInstance.__init__(self)
        GeneratorQueryHandler.__init__(self)

        self.fuzzy: bool = False

        self._match_path: bool
        if (match_path := self.readConfig("match_path", bool)) is None:
            self._match_path = True
        else:
            self._match_path = cast(bool, match_path)

        if platform == "darwin":
            zed_dir_name = "Zed"
            icon = "/Applications/Zed.app"
            icon_preview = "/Applications/Zed-Preview.app"
        elif platform == "linux":
            zed_dir_name = "zed"
            icon = "zed"
            icon_preview = "zed-preview"
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

    @property
    def match_path(self) -> bool:
        return self._match_path

    @match_path.setter
    def match_path(self, value: bool):
        self._match_path = value
        self.writeConfig("match_path", value)

    @override
    def supportsFuzzyMatching(self):
        return True

    @override
    def setFuzzyMatching(self, enabled: bool):
        self.fuzzy = enabled

    @override
    def defaultTrigger(self) -> str:
        return "zd "

    @override
    def synopsis(self, query: str) -> str:
        return "<workspace name|path>" if self._match_path else "<workspace name>"

    @override
    def items(self, context: QueryContext) -> Generator[list[Item]]:
        if not context.isValid:
            return

        editor_workspace_pairs: list[tuple[Editor, Workspace]] = []
        m = Matcher(context.query, MatchConfig(fuzzy=self.fuzzy))

        for editor in self.editors:
            workspaces = editor.list_workspaces()
            workspaces: list[Workspace] = [p for p in workspaces if Path(p.path).exists()]
            if self._match_path:
                workspaces = [p for p in workspaces if m.match(p.name) or m.match(p.path)]
            else:
                workspaces = [p for p in workspaces if m.match(p.name)]

            editor_workspace_pairs.extend([(editor, p) for p in workspaces])

        # sort by last opened
        editor_workspace_pairs.sort(key=lambda pair: pair[1].last_opened, reverse=True)
        items: list[StandardItem] = [self._make_item(editor, workspace) for editor, workspace in editor_workspace_pairs]

        yield items

    def _make_item(self, editor: Editor, workspace: Workspace) -> StandardItem:
        actions: list[Action] = [
            Action(
                "open",
                "Open in %s" % editor.name,
                lambda selected_workspace=workspace.path: runDetachedProcess(
                    # Binary has to be valid here
                    [editor.binary, selected_workspace],  # pyright: ignore[reportArgumentType]  # ty:ignore[invalid-argument-type]
                    selected_workspace,
                ),
            ),
            Action(
                "open-terminal",
                "Open Terminal at path",
                lambda selected_workspace=workspace.path: runTerminal(f"cd {selected_workspace} && exec $SHELL"),
            ),
            Action(
                "open-file-manager",
                "Open File Manager at path",
                lambda selected_workspace=workspace.path: openFile(selected_workspace),
            ),
        ]

        return StandardItem(
            id=f"{workspace.id}-{editor.binary}-{workspace.last_opened}",
            text=workspace.name,
            subtext=workspace.path,
            input_action_text=workspace.name,
            icon_factory=lambda: Icon.theme(editor.icon),
            actions=actions,
        )

    @override
    def configWidget(self):
        return [
            {"type": "label", "text": str(__doc__).strip(), "widget_properties": {"textFormat": "Qt::MarkdownText"}},
            {"type": "checkbox", "property": "match_path", "label": "Match path"},
        ]
