import collections
import os
import subprocess
import sys
import threading

from shutil import which

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

import xml.etree.ElementTree as etree
import xdg.IconTheme
import xdg.Menu


def log(text):
    sys.stdout.write(str(text) + "\n")


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
    p = subprocess.Popen(cmd, stdin=open(os.devnull))
    t = threading.Thread(target=p.wait)
    t.setDaemon(True)
    t.start()


def launch(action):
    if which("kioclient"):
        _run_and_forget(["kioclient", "exec", action])
    elif which("gtk-launch"):
        _run_and_forget(["gtk-launch", action])
    else:
        # FIXME make error dialog
        log("Cannot launch %s as no launch program is installed" % action)


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


class ExternalProgramListing(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        self.xdg_menu_items = kwargs.pop("items")
        xbmcgui.WindowXML.__init__(self)

    def onInit(self):
        xbmc.executebuiltin("Container.SetViewMode(55)")
        listitems = []
        for action, title, comment, icon in sorted(
            self.xdg_menu_items, key=lambda x: x[1].lower()
        ):
            listitems.append(xbmcgui.ListItem(title, comment))
            listitems[-1].setProperty("action", action)
            if icon:
                listitems[-1].setArt({"icon": icon})
        # now we are going to add all the items we have defined to the (built-in) container
        self.addItems(listitems)
        # give kodi a bit of (processing) time to add all items to the container
        xbmc.sleep(100)
        # this puts the focus on the top item of the container
        self.setFocusId(self.getCurrentContainerId())

    def onClick(self, controlId):
        if controlId == self.getCurrentContainerId():
            item = self.getListItem(self.getCurrentListPosition())
            action = item.getProperty("action")
            try:
                base = os.path.basename(action)
                if base in preruns:
                    prerun = preruns[base]
                    try:
                        subprocess.check_call(prerun)
                    except subprocess.CalledProcessError:
                        launch(action)
                else:
                    launch(action)
            finally:
                self.close()


def _main(*args):
    ADDON = xbmcaddon.Addon(id="script.xdgmenu")
    handle = int(sys.argv[1])
    second_arg = args[1]
    third_arg = args[2]
    cwd = ADDON.getAddonInfo("path")

    if second_arg:
        log(args)
        globals()[args[0]](*args[1:])
    else:
        for action, title, comment, icon in sorted(
            read_xdg_menu(), key=lambda x: x[1].lower()
        ):
            li = xbmcgui.ListItem(title, comment, action)
            li.setProperty("action", action)
            if icon:
                li.setArt({"icon": icon})
            xbmcplugin.AddDirectoryItem(
                handle=handle,
                url=action,
                listitem=li,
            )
        xbmcplugin.endOfDirectory(handle)


if __name__ == "__main__":
    _main(*sys.argv[1:])
