import collections
import os
import urllib.parse
import subprocess
import sys
import threading

from shutil import which
from xbmc import log

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

import xml.etree.ElementTree as etree
import xdg.IconTheme
import xdg.Menu


class LenientXMLMenuBuilder(xdg.Menu.XMLMenuBuilder):
    def parse(self, filename=None):
        """Load an applications.menu file.

        filename : str, optional
          The default is ``$XDG_CONFIG_DIRS/menus/${XDG_MENU_PREFIX}applications.menu``.
        """
        # convert to absolute path
        if filename and not os.path.isabs(filename):
            filename = xdg.Menu._get_menu_file_path(filename)
        # use default if no filename given
        if not filename:
            candidate = os.environ.get("XDG_MENU_PREFIX", "") + "applications.menu"
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
            log(xdg.Menu.ParsingError("Not a valid .menu file", filename))
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
                if not x.DesktopEntry.getHidden() and not x.DesktopEntry.getNoDisplay():
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
            "Cannot launch %s as no launch program (kioclient or gtk-launch) is installed."
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
    addon = xbmcaddon.Addon(id="script.xdgmenu")
    handle = int(sys.argv[1])
    second_arg = args[1]
    unused_third_arg = args[2]

    for i in range(len(args)):
        log('addon_argv[{}] "{}"'.format(i, args[i]))

    if second_arg:
        args = urllib.parse.parse_qs(second_arg[1:])
        if "launch" in args:
            launch(args["launch"][0])
        else:
            raise Exception("Unknown args: %s" % args)
    else:
        for path, title, comment, icon in sorted(
            read_xdg_menu(), key=lambda x: x[1].lower()
        ):
            li = xbmcgui.ListItem(title, comment)
            li.setProperty("IsPlayable", "True")
            if icon:
                li.setArt({"icon": icon})
            url = build_url(sys.argv[0], {"launch": path})
            xbmcplugin.addDirectoryItem(
                handle=handle,
                url=url,
                listitem=li,
                isFolder=False,
            )
        xbmcplugin.endOfDirectory(handle)


if __name__ == "__main__":
    _main(*sys.argv[1:])
