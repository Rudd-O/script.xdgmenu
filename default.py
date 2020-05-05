import collections
import os
import subprocess
import sys
import threading

import xdg.IconTheme
import xdg.Menu

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xml.etree.ElementTree as etree


ADDON = xbmcaddon.Addon(id="script.xdgmenu")
ADDON_HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else None
CWD = ADDON.getAddonInfo("path")


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


def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


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


def log(text):
    return
    with open("/tmp/x", "a") as f:
        f.write(str(text) + "\n")


class ExternalProgramListing(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        self.xdg_menu_items = kwargs.pop("items")
        xbmcgui.WindowXML.__init__(self)

    def onInit(self):
        xbmc.executebuiltin("Container.SetViewMode(50)")
        listitems = []
        for action, title, comment, icon in self.xdg_menu_items:
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
                        _run_and_forget(["kioclient", "exec", action])
                else:
                    _run_and_forget(["kioclient", "exec", action])
            finally:
                self.close()


def _main(*args):
    if args:
        log(args)
        globals()[args[0]](*args[1:])
    else:
        items = read_xdg_menu()
        win = ExternalProgramListing(
            "programlisting.xml", CWD, "Default", "1080i", items=items
        )
        win.doModal()


if __name__ == "__main__":
    _main(*sys.argv[1:])
