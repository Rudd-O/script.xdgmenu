import collections
import os
import urllib.parse
import subprocess
import sys
import threading

from shutil import which
from xbmc import log  # type: ignore

import xbmcaddon  # type: ignore
import xbmcgui  # type: ignore
import xbmcplugin  # type: ignore

import xml.etree.ElementTree as etree
import xdg.IconTheme
import xdg.Menu


class LenientXMLMenuBuilder(xdg.Menu.XMLMenuBuilder):
    def parse(self, filename=None):
        """Load an applications.menu file.

        filename : str, optional
          The default is
          ``$XDG_CONFIG_DIRS/menus/${XDG_MENU_PREFIX}applications.menu``.
        """
        # convert to absolute path
        if filename and not os.path.isabs(filename):
            filename = xdg.Menu._get_menu_file_path(filename)
        # use default if no filename given
        if not filename:
            menuprefix = os.environ.get("XDG_MENU_PREFIX", "")
            candidate = menuprefix + "applications.menu"
            filename = xdg.Menu._get_menu_file_path(candidate)
        if not filename:
            raise xdg.Menu.ParsingError(
                "File not found", "/etc/xdg/menus/%s" % candidate
            )
        # check if it is a .menu file
        if not filename.endswith(".menu"):
            raise xdg.Menu.ParsingError("Not a .menu file", filename)
        # create xml parser
        try:
            tree = etree.parse(filename)
        except Exception as e:
            log(
                str(
                    xdg.Menu.ParsingError(
                        "Not a valid .menu file: %s" % e,
                        filename,
                    )
                )
            )
            tree = etree.fromstring("<Menu></Menu>")

        # parse menufile
        self._merged_files = set()
        self._directory_dirs = set()
        self.cache = xdg.Menu.MenuEntryCache()

        menu = self.parse_menu(tree.getroot(), filename)
        menu.tree = tree
        menu.filename = filename

        self.handle_moves(menu)
        self.post_parse(menu)

        # generate the menu
        self.generate_not_only_allocated(menu)
        self.generate_only_allocated(menu)

        # and finally sort
        menu.sort()

        return menu


def read_xdg_menu():
    def recurse(x):
        entries = []
        try:
            x.Name
        except AttributeError:
            try:
                hidden = x.DesktopEntry.getHidden()
                nodisplay = x.DesktopEntry.getNoDisplay()
                if not hidden and not nodisplay:
                    if not x.DesktopEntry.getTryExec() or which(
                        x.DesktopEntry.getTryExec()
                    ):
                        entries.append(
                            [
                                x.DesktopEntry.filename,
                                x.DesktopEntry.getName(),
                                x.DesktopEntry.getComment(),
                                x.DesktopEntry.getIcon(),
                            ]
                        )
            except AttributeError:
                pass
        subentries = []
        if hasattr(x, "Entries"):
            for subx in x.Entries:
                subentries.extend(recurse(subx))
        return entries + subentries

    m = LenientXMLMenuBuilder().parse()
    menuitems = recurse(m)
    new_menuitems = collections.OrderedDict()
    for item in menuitems:
        if os.path.basename(item[0]) in new_menuitems:
            if item[0] != new_menuitems[os.path.basename(item[0])][0]:
                log(
                    "Not including %s because %s is already in there"
                    % (item[0], new_menuitems[os.path.basename(item[0])])[0]
                )
        # the icon at the end
        item[-1] = xdg.IconTheme.getIconPath(item[-1])
        new_menuitems[os.path.basename(item[0])] = item
    return list(new_menuitems.values())


def _run_and_forget(cmd):
    try:
        p = subprocess.Popen(cmd, stdin=open(os.devnull))
    except Exception as e:
        xbmcgui.Dialog().notification(
            "Cannot launch program",
            "An error happened when launching a program (%s)" % (e,),
        )
    t = threading.Thread(target=p.wait)
    t.setDaemon(True)
    t.start()


def run_desktop_file(desktop_file):
    if which("kioclient"):
        _run_and_forget(["kioclient", "exec", desktop_file])
    elif which("gtk-launch"):
        _run_and_forget(["gtk-launch", desktop_file])
    else:
        xbmcgui.Dialog().notification(
            "Cannot launch program",
            (
                "Cannot launch %s as no launch program"
                + " (kioclient or gtk-launch) is installed."
            )
            % (os.path.basename(desktop_file)),
        )


preruns = {
    "google-chrome.desktop": [
        "bash",
        "-c",
        """
if xdotool search --desktop 0 --all --class --name Chrome windowactivate ; then
  exit
fi
exit 1
""",
    ]
}


def launch(desktop_file):
    prerun = preruns.get(os.path.basename(desktop_file), None)
    if prerun:
        try:
            subprocess.check_call(prerun)
        except subprocess.CalledProcessError:
            run_desktop_file(desktop_file)
    else:
        run_desktop_file(desktop_file)


def encodepath(path):
    return urllib.parse.quote(path)


def build_url(base, query):
    return base + "?" + urllib.parse.urlencode(query)


def _main(*args):
    addon = xbmcaddon.Addon(id="script.xdgmenu")  # noqa
    log("script.xdgmenu starting")
    for i in range(len(args)):
        log("addon_argv[{}] = {}".format(i, args[i]))

    handle = int(args[0])
    second_arg = args[1]
    third_arg = args[2] if len(args) > 2 else None  # noqa

    if second_arg:
        qs = urllib.parse.parse_qs(second_arg[1:])
    else:
        qs = {}

    for k, v in qs.items():
        log("qs[{}] = {}".format(k, v))

    if "launch" in qs:
        launch(qs["launch"][0])
    else:
        for path, title, comment, icon in sorted(
            read_xdg_menu(), key=lambda x: x[1].lower()
        ):
            url = build_url(sys.argv[0], {"launch": path})
            li = xbmcgui.ListItem(title, comment)
            li.setPath(url)
            if icon:
                li.setArt({"icon": icon})
            xbmcplugin.addDirectoryItem(
                handle=handle,
                url=url,
                listitem=li,
                isFolder=False,
            )
        xbmcplugin.endOfDirectory(handle)


if __name__ == "__main__":
    _main(*sys.argv[1:])
