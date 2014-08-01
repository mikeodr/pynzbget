# -*- encoding: utf-8 -*-
#
# A scripting wrapper for NZBGet Post and Pre Processing
#
# Copyright (C) 2014 Chris Caron <lead2gold@gmail.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
"""
This class was intended to make writing NZBGet Scripts easier to manage and
write by handling the common error handling and provide the most reused code
in a re-usable container. It was initially written to work with NZBGet v13
but provides most backwards compatibility.

It was designed to be inheritied as a base class requiring you to only write
the main() function which should preform the task you are intending.

It looks after fetching all of the environment variables and will parse
the meta information out of the NZB File.

It allows you to set variables that other scripts can access if they need to
using the set() and get() variables. This is done through a simply self
maintained hash table type structure within a sqlite database. All the
wrapper functions are already written.  If you call 'set('MYKEY', 1')
you can call get('MYKEY') in another script and continue working

push() functions written to pass information back to nzbget using it's
processing engine.

all exceptions are now automatically handled and logging can be easily
changed from stdout, to stderr or to a file.

Test suite built in (using python-nose) to ensure old global variables
will still work as well as make them easier to access and manipulate.

Some inline documentation was based on content provided at:
   - http://nzbget.net/Extension_scripts


############################################################################
Scan Script Usage/Example
############################################################################

############################################################################
### NZBGET SCAN SCRIPT                                                   ###
#
# Describe your Scan Script here
# Author: Chris Caron <lead2gold@gmail.com>
#

############################################################################
### OPTIONS                                                              ###

#
# Enable NZBGet debug logging (yes, no)
# Debug=no
#

### NZBGET SCAN SCRIPT                                                   ###
############################################################################

from NZBGet import ScanScript

# Now define your class while inheriting the rest
class MyScanScript(ScanScript):
    def main(self):

        # Version Checking, Environment Variables Present, etc
        if not self.validate():
            # No need to document a failure, validate will do that
            # on the reason it failed anyway
            return False

        # write all of your code here you would have otherwise put in the
        # script

        # All system environment variables (NZBOP_.*) as well as Post
        # Process script specific content (NZBNP_.*)
        # following dictionary (without the NZBOP_ or NZBNP_ prefix):
        print 'TEMPDIR (directory is: %s' % self.get('TEMPDIR')
        print 'DIRECTORY %s' self.get('DIRECTORY')
        print 'FILENAME %s' self.get('FILENAME')
        print 'NZBNAME %s' self.get('NZBNAME')
        print 'CATEGORY %s' self.get('CATEGORY')
        print 'PRIORITY %s' self.get('PRIORITY')
        print 'TOP %s' self.get('TOP')
        print 'PAUSED %s' self.get('PAUSED')

        # Set any variable you want by any key.  Note that if you use
        # keys that were defined by the system (such as CATEGORY, DIRECTORY,
        # etc, you may have some undesirable results.  Try to avoid reusing
        # system variables already defined (identified above):
        self.set('MY_VAR', 'MY_VALUE')

        # You can fetch it back; this will also set an entry in  the
        # sqlite database for each hash references that can be pulled from
        # another script that simply calls self.get('MY_VAR')
        print self.get('MY_VAR') # prints MY_VALUE

        # You can also use push() which is similar to set()
        # except that it interacts with the NZBGet Server and does not use
        # the sqlite database. This can only be reached across other
        # scripts if the calling application is NZBGet itself
        self.push('ANOTHER_VAR', 'ANOTHER_VALUE')

        # You can still however locally retrieve what you set using push()
        # with the get() function
        print self.get('ANOTHER_VAR') # prints ANOTHER_VALUE

        # Your script configuration files (NZBNP_.*) are here in this
        # dictionary (again without the NZBNP_ prefix):
        # assume you defined `Debug=no` in the first 10K of your ScanScript
        # NZBGet translates this to `NZBNP_DEBUG` which can be retrieved
        # as follows:
        print 'DEBUG %s' self.config.get('DEBUG')

        # Returns have been made easy.  Just return:
        #   * True if everything was successful
        #   * False if there was a problem
        #   * None if you want to report that you've just gracefully
                  skipped processing (this is better then False)
                  in some circumstances. This is neither a failure or a
                  success status.

        # Feel free to use the actual exit codes as well defined by
        # NZBGet on their website.  They have also been defined here
        # from nzbget.ScriptBase import EXIT_CODE

        return True

# Call your script as follows:
if __name__ == "__main__":
    from sys import exit

    # Create an instance of your Script
    scanscript = MyScanScript()

    # call run() and exit() using it's returned value
    exit(scanscript.run())

"""
import re
from os import environ
from os.path import isdir
from os.path import isfile
from os.path import exists
from os.path import basename

# Relative Includes
from ScriptBase import ScriptBase

class PRIORITY(object):
    """Although priority can be any integer value, the web-interface operates
    with six predefined priorities.
    """
    VERY_LOW = -100
    LOW = -50
    NORMAL = 0
    HIGH = 50
    VERY_HIGH = 100
    FORCE = 900

# A list of priorities makes it easier to validate them
# for each priority added above, make sure you also update this list.
PRIORITIES = (
    PRIORITY.VERY_LOW,
    PRIORITY.LOW,
    PRIORITY.NORMAL,
    PRIORITY.HIGH,
    PRIORITY.VERY_HIGH,
    PRIORITY.FORCE,
)

# Environment variable that prefixes all NZBGET options being passed into
# scripts with respect to the NZB File (used in Scan Scripts)
SCAN_ENVIRO_ID = 'NZBNP_'

# Precompile Regulare Expression for Speed
SCAN_OPTS_RE = re.compile('^%s([A-Z0-9_]+)$' % SCAN_ENVIRO_ID)

class ScanScript(ScriptBase):
    def __init__(self, directory=None, nzbname=None, filename=None,
                 category=None, priority=None, top=None, paused=None,
                 # Parse specified NZBFile and extrat meta information
                 parse_nzbfile=True,
                 # Use SQLite Database
                 use_database=True,
                 # Logging
                 logger=True, debug=False):
        """variables defined as none we attempt to extract from the
        environment. If you want to avoid extracting content from the
        environment, set the value to 'False' or even a blank string ''
        will acomplish this for you.
        """
        # Initialize Base Class
        super(ScanScript, self).__init__(logger=logger, debug=debug)

        # Fetch/Load Post Process Script Configuration
        self.system = dict(self.system.items() + \
              [(SCAN_OPTS_RE.match(k).group(1), v.strip()) \
               for (k, v) in environ.items() if SCAN_OPTS_RE.match(k)])

        # self.directory
        # This is the path to the destination directory for downloaded files.
        if directory is None:
            self.directory = environ.get(
                '%sDIRECTORY' % SCAN_ENVIRO_ID,
            )
        else:
            self.directory = directory

        # self.nzbname
        # User-friendly name of processed nzb-file as it is displayed by the
        # program.  The file path and extension are removed.  If download was
        # renamed, this parameter reflects the new name.
        if nzbname is None:
            self.nzbname = environ.get(
                '%sNZBNAME' % SCAN_ENVIRO_ID,
            )
        else:
            self.nzbname = nzbname

        # self.filename
        # Name of file to be processed
        if filename is None:
            self.filename = environ.get(
                '%sFILENAME' % SCAN_ENVIRO_ID,
            )
        else:
            self.filename = filename

        # self.category
        # Category assigned to nzb-file (can be empty string).
        if category is None:
            self.category = environ.get(
                '%sCATEGORY' % SCAN_ENVIRO_ID,
            )
        else:
            self.category = category

        # self.priority
        # The priority of the nzb file being scanned
        if priority is None:
            self.priority = environ.get(
                '%sPRIORITY' % SCAN_ENVIRO_ID,
            )
        else:
            self.priority = priority

        # self.top
        # Flag indicating that the file will be added to the top of queue
        if top is None:
            self.top = environ.get(
                '%sTOP' % SCAN_ENVIRO_ID,
            )
        else:
            self.top = top

        # self.paused
        # Flag indicating that the file will be added as paused
        if paused is None:
            self.paused = environ.get(
                '%sPAUSED' % SCAN_ENVIRO_ID,
            )
        else:
            self.paused = paused

        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        # Error Handling
        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        if not (exists(self.directory) and isdir(self.directory)):
            self.logger.warning('Process directory is missing: %s' % \
                self.directory)

        if not self.filename:
            raise EnvironmentError(
                '%sFILENAME variable was not defined' % SCAN_ENVIRO_ID
            )

        if not isfile(self.filename):
            self.logger.warning('NZB File not found: %s' % self.filename)

        elif parse_nzbfile:
            # Initialize information fetched from NZB File
            self.nzbheaders = self.parse_nzbfile(self.filename)

        # Priority
        if not isinstance(self.priority, int):
            try:
                self.priority = int(self.priority)
            except:
                self.priority = PRIORITY.NORMAL

        if self.priority not in PRIORITIES:
            self.priority = PRIORITY.NORMAL

        # Top
        try:
            self.top = bool(int(self.top))
        except:
            self.top = False

        # Paused
        try:
            self.paused = bool(int(self.paused))
        except:
            self.paused = False

        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        # Enforce system/global variables for script processing
        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        self.system['DIRECTORY'] = self.directory
        environ['%sDIRECTORY' % SCAN_ENVIRO_ID] = self.directory

        self.system['NZBNAME'] = self.nzbname
        environ['%sNZBNAME' % SCAN_ENVIRO_ID] = self.nzbname

        self.system['FILENAME'] = self.filename
        environ['%sFILENAME' % SCAN_ENVIRO_ID] = self.filename

        self.system['CATEGORY'] = self.category
        environ['%sCATEGORY' % SCAN_ENVIRO_ID] = self.category

        self.system['PRIORITY'] = self.priority
        environ['%sPRIORITY' % SCAN_ENVIRO_ID] = str(self.priority)

        self.system['TOP'] = self.top
        environ['%sTOP' % SCAN_ENVIRO_ID] = str(int(self.top))

        self.system['PAUSED'] = self.paused
        environ['%sPAUSED' % SCAN_ENVIRO_ID] = str(int(self.paused))

        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        # Create Database for set() and get() operations
        # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
        if use_database:
            # database_key is inherited in the parent class
            # future calls of set() and get() will allow access
            # to the database now
            self.database_key = basename(self.filename)

    # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # File Retrieval
    # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def get_files(self, search_dir=None, regex_filter=None, prefix_filter=None,
                    suffix_filter=None, fullstats=False):
        """a wrapper to the get_files() function defined in the inherited class
           the only difference is the search_dir automatically uses the
           defined download `directory` as a default (if not specified).
        """
        if search_dir is None:
            search_dir = self.directory

        return super(ScanScript, self).get_files(
            search_dir=search_dir,
            regex_filter=regex_filter,
            prefix_filter=prefix_filter,
            suffix_filter=suffix_filter,
            fullstats=fullstats,
        )

    # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    # Set/Control Functions (also passes data back to NZBGet)
    # =-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
    def push_nzbname(self, nzbname=None):
        if nzbname:
            # Update local nzbname
            self.nzbname = nzbname

            # Accomodate other environmental variables
            self.system['NZBNAME'] = self.nzbname
            environ['%sNZBNAME' % SCAN_ENVIRO_ID] = self.nzbname

        # Alert NZBGet of Change
        return self._push(
            key='NZBNAME',
            value=self.nzbname,
        )

    def push_category(self, category=None):
        if category:
            # Update local category
            self.category = category

            # Accomodate other environmental variables
            self.system['CATEGORY'] = self.category
            environ['%sCATEGORY' % SCAN_ENVIRO_ID] = self.category

        # Alert NZBGet of Change
        return self._push(
            key='CATEGORY',
            value=self.category,
        )

    def push_priority(self, priority=None):

        if priority is not None:
            if priority not in PRIORITIES:
                return False

            # Update local priority
            self.priority = priority

            # Accomodate other environmental variables
            self.system['PRIORITY'] = self.priority
            environ['%sPRIORITY' % SCAN_ENVIRO_ID] = str(self.priority)

        # Alert NZBGet of Change
        return self._push(
            key='PRIORITY',
            value=self.priority,
        )

    def push_top(self, top=None):

        if top is not None:
            # Update local priority
            try:
                self.top = bool(int(top))
            except:
                return False

            # Accomodate other environmental variables
            self.system['TOP'] = self.top
            environ['%sTOP' % SCAN_ENVIRO_ID] = str(int(self.top))

        # Alert NZBGet of Change
        return self._push(
            key='TOP',
            # Convert bool to int for response
            value=int(self.top),
        )

    def push_paused(self, paused=None):

        if paused is not None:
            # Update local priority
            try:
                self.paused = bool(int(paused))
            except:
                return False

            # Accomodate other environmental variables
            self.system['PAUSED'] = self.paused
            environ['%sPAUSED' % SCAN_ENVIRO_ID] = str(int(self.paused))

        # Alert NZBGet of Change
        return self._push(
            key='PAUSED',
            # Convert bool to int for response
            value=int(self.paused),
        )
