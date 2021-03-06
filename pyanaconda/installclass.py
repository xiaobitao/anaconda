#
# installclass.py:  This is the prototypical class for workstation, server, and
# kickstart installs.  The interface to BaseInstallClass is *public* --
# ISVs/OEMs can customize the install by creating a new derived type of this
# class.
#
# Copyright (C) 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007
# Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from distutils.sysconfig import get_python_lib
import os, sys
import imp

from blivet.partspec import PartSpec
from blivet.autopart import swap_suggestion
from blivet.platform import platform
from blivet.size import Size

from pyanaconda.anaconda_loggers import get_module_logger
log = get_module_logger(__name__)

from pyanaconda.kickstart import getAvailableDiskSpace
from pyanaconda.constants import STORAGE_SWAP_IS_RECOMMENDED
from pykickstart.constants import FIRSTBOOT_DEFAULT

class BaseInstallClass(object):
    # default to not being hidden
    hidden = False
    name = "base"
    bootloaderTimeoutDefault = None
    bootloaderExtraArgs = []

    # Anaconda flags several packages to be installed based on the configuration
    # of the system -- things like fs utilities, bootloader, &c. This is a list
    # of packages that we should not try to install using the aforementioned
    # mechanism.
    ignoredPackages = []

    # This flag controls whether or not Anaconda should provide an option to
    # install the latest updates during installation source selection.
    installUpdates = True

    _l10n_domain = None

    # The default filesystem type to use.  If None, we will use whatever
    # Blivet uses by default.
    defaultFS = None

    # help
    help_folder = "/usr/share/anaconda/help"
    help_main_page = "Installation_Guide.xml"
    help_main_page_plain_text = "Installation_Guide.txt"
    help_placeholder = None
    help_placeholder_with_links = None
    help_placeholder_plain_text = None

    # path to the installclass stylesheet, if any
    stylesheet = None

    # comps environment id to select by default
    defaultPackageEnvironment = None

    # state firstboot should be in unless something special happens
    firstboot = FIRSTBOOT_DEFAULT

    @property
    def l10n_domain(self):
        if self._l10n_domain is None:
            raise RuntimeError("Localization domain for '%s' not set." %
                               self.name)
        return self._l10n_domain

    def setPackageSelection(self, anaconda):
        pass

    def getBackend(self):
        # The default is to return None here, which means anaconda should
        # use live or dnf (whichever can be detected).  This method is
        # provided as a way for other products to specify their own.
        return None

    def setDefaultPartitioning(self, storage):
        autorequests = [PartSpec(mountpoint="/", fstype=storage.default_fstype,
                                 size=Size("1GiB"),
                                 max_size=Size("50GiB"),
                                 grow=True,
                                 btr=True, lv=True, thin=True, encrypted=True),
                        PartSpec(mountpoint="/home",
                                 fstype=storage.default_fstype,
                                 size=Size("500MiB"), grow=True,
                                 required_space=Size("50GiB"),
                                 btr=True, lv=True, thin=True, encrypted=True)]

        bootreqs = platform.set_default_partitioning()
        if bootreqs:
            autorequests.extend(bootreqs)


        disk_space = getAvailableDiskSpace(storage)
        swp = swap_suggestion(disk_space=disk_space)
        autorequests.append(PartSpec(fstype="swap", size=swp, grow=False,
                                     lv=True, encrypted=True))

        for autoreq in autorequests:
            if autoreq.fstype is None:
                if autoreq.mountpoint == "/boot":
                    autoreq.fstype = storage.default_boot_fstype
                else:
                    autoreq.fstype = storage.default_fstype

        storage.autopart_requests = autorequests

    def customizeDefaultPartitioning(self, storage, data):
        # Customize the default partitioning with kickstart data.
        skipped_mountpoints = set()
        skipped_fstypes = set()

        # Create sets of mountpoints and fstypes to remove from autorequests.
        if data.autopart.autopart:
            # Remove /home if --nohome is selected.
            if data.autopart.nohome:
                skipped_mountpoints.add("/home")

            # Remove /boot if --noboot is selected.
            if data.autopart.noboot:
                skipped_mountpoints.add("/boot")

            # Remove swap if --noswap is selected.
            if data.autopart.noswap:
                skipped_fstypes.add("swap")

                # Swap will not be recommended by the storage checker.
                from pyanaconda.storage_utils import storage_checker
                storage_checker.add_constraint(STORAGE_SWAP_IS_RECOMMENDED, False)

        # Skip mountpoints we want to remove.
        storage.autopart_requests = [req for req in storage.autopart_requests
                                     if req.mountpoint not in skipped_mountpoints
                                     and req.fstype not in skipped_fstypes]

    def configure(self, anaconda):
        anaconda.bootloader.timeout = self.bootloaderTimeoutDefault
        anaconda.bootloader.boot_args.update(self.bootloaderExtraArgs)

        # The default partitioning should be always set.
        self.setDefaultPartitioning(anaconda.storage)

        # Customize the default partitioning with kickstart data.
        self.customizeDefaultPartitioning(anaconda.storage, anaconda.ksdata)

    def setStorageChecker(self, storage_checker):
        # Update constraints and add or remove some checks in
        # the storage checker to customize the storage sanity
        # checking.
        pass

    # sets default ONBOOT values and updates ksdata accordingly
    def setNetworkOnbootDefault(self, ksdata):
        pass

    def __init__(self):
        pass

allClasses = []
allClasses_hidden = []

# returns ( className, classObject ) tuples
def availableClasses(showHidden=False):
    global allClasses
    global allClasses_hidden

    if not showHidden:
        if allClasses:
            return allClasses
    else:
        if allClasses_hidden:
            return allClasses_hidden

    path = []

    env_path = []
    if "ANACONDA_INSTALL_CLASSES" in os.environ:
        env_path += os.environ["ANACONDA_INSTALL_CLASSES"].split(":")

    for d in env_path + ["installclasses",
              "/tmp/updates/pyanaconda/installclasses",
              "/tmp/product/pyanaconda/installclasses",
              "%s/pyanaconda/installclasses" % get_python_lib(plat_specific=1)]:
        if os.access(d, os.R_OK):
            path.append(d)

    # append the location of installclasses to the python path so we
    # can import them
    sys.path = path + sys.path

    files = []
    for p in reversed(path):
        files += os.listdir(p)

    done = {}
    lst = []
    for fileName in files:
        if fileName[0] == '.':
            continue
        if len(fileName) < 4:
            continue
        if fileName[-3:] != ".py" and fileName[-4:-1] != ".py":
            continue
        mainName = fileName.split(".")[0]
        if mainName in done:
            continue
        done[mainName] = 1

        try:
            found = imp.find_module(mainName)
        except ImportError:
            log.warning("module import of %s failed: %s", mainName, sys.exc_info()[0])
            continue

        try:
            loaded = imp.load_module(mainName, found[0], found[1], found[2])

            for (_key, obj) in loaded.__dict__.items():
                # If it's got these two methods, it's an InstallClass.
                if hasattr(obj, "setDefaultPartitioning") and hasattr(obj, "setPackageSelection"):
                    sortOrder = getattr(obj, "sortPriority", 0)
                    if not obj.hidden or showHidden:
                        lst.append(((obj.name, obj), sortOrder))
        except (ImportError, AttributeError):
            log.warning("module import of %s failed: %s", mainName, sys.exc_info()[0])

    # sort by sort order first, then by install class name
    lst.sort(key=lambda x: (x[1], x[0][0]))
    for (item, _) in lst:
        if showHidden:
            allClasses_hidden += [item]
        else:
            allClasses += [item]

    if showHidden:
        return allClasses_hidden
    else:
        return allClasses

def getBaseInstallClass():
    # figure out what installclass we should base on.
    allavail = availableClasses(showHidden=True)
    avail = availableClasses(showHidden=False)

    if len(avail) == 1:
        (cname, cobject) = avail[0]
        log.info("using only installclass %s", cname)
    elif len(allavail) == 1:
        (cname, cobject) = allavail[0]
        log.info("using only installclass %s", cname)

    # Use the highest priority install class if more than one found.
    elif len(avail) > 1:
        (cname, cobject) = avail.pop()
        log.info('%s is the highest priority installclass, using it', cname)
    elif len(allavail) > 1:
        (cname, cobject) = allavail.pop()
        log.info('%s is the highest priority installclass, using it', cname)
    else:
        raise RuntimeError("Unable to find an install class to use!!!")

    return cobject

baseclass = getBaseInstallClass()

# we need to be able to differentiate between this and custom
class DefaultInstall(baseclass):
    def __init__(self):
        baseclass.__init__(self)
