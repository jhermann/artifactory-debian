# -*- coding: utf-8 -*-
""" WebDAV upload method for dput.

    Install to "/usr/share/dput/webdav.py".
"""
from __future__ import with_statement
import os, sys, httplib, urllib2, urlparse, getpass, cgi
from contextlib import closing

try:
    import dputhelper
except ImportError:
    sys.path.insert(0, "/usr/share/dput/helper")
    import dputhelper


def trace(msg, **kwargs):
    """Emit log traces in debug mode."""
    if trace.debug:
        print("D: webdav: " + (msg % kwargs))
trace.debug = False


def _resolve_credentials(login):
    """Look up special forms of credential references."""
    result = login
    if "$" in result:
        result = os.path.expandvars(result)
    if result.startswith("file:"):
        result = os.path.abspath(os.path.expanduser(result.split(':', 1)[1]))
        with closing(open(result, "r")) as handle:
            result = handle.read().strip()
    trace("Resolved login credentials to %(user)s:%(pwd)s", 
        user=result.split(':', 1)[0], pwd='*' * len(result.split(':', 1)[1]), )
    return result


class PromptingPasswordMgr(urllib2.HTTPPasswordMgr):
    """ Custom password manager that prompts for a password once, if none is available otherwise.
        
        Based on code in dput 0.9.6 (http method).
    """

    def __init__(self, login):
        super(PromptingPasswordMgr, self).__init__()
        self.login = login

    def find_user_password(self, realm, authuri):
        """Prompt for a password once and remember it, unless already provided in the configuration."""
        authuri = self.reduce_uri(authuri)[0]
        authinfo = super(PromptingPasswordMgr, self).find_user_password(realm, authuri)

        if authinfo == (None, None):
            credentials = self.login
            if ':' in credentials:
                authinfo = credentials.split(':', 1)
            else:
                password = getpass.getpass("    Password for %s:" % realm)
                self.add_password(realm, authuri, credentials, password)
                authinfo = credentials, password

        return authinfo


def get_host_argument(fqdn):
    """ We have to jump through several hoops to get to our config section,
        which in turn is the only place where the host argument is available.
    """
    import __main__ as dput # if only we would get passed our config section...

    result = ""
    for section in dput.config.sections():
        if (dput.config.has_option(section, "fqdn")
                and dput.config.get(section, "fqdn") == fqdn
                and dput.config.has_option(section, section)):
            result = dput.config.get(section, section)

    return result


def upload(fqdn, login, incoming, files_to_upload, debug, dummy, progress=0):
    """Upload the files via WebDAV."""
    assert sys.version_info >= (2, 5), "Your snake is a rotting corpse"
    trace.debug = bool(debug)
    login = _resolve_credentials(login)

    # Try to get host argument from command line
    if upload.extended_info:
        host_config = dict(upload.extended_info["config"].items(upload.extended_info["host"]))
        host_argument = host_config.get(upload.extended_info["host"], "")
    else:
        host_config = {}
        host_argument = get_host_argument(fqdn)
    cli_params = dict(cgi.parse_qsl(host_argument, keep_blank_values=True))

    # Special handling for integration test code
    if "integration-test" in cli_params:
        import pprint
        print "upload arguments = ",
        pprint.pprint(dict((k, v) for k, v in locals().iteritems() if k in (
            "fqdn", "login", "incoming", "files_to_upload", "debug", "dummy", "progress")))
        print "host config = ",
        pprint.pprint(host_config)
        print "host arguments = ",
        pprint.pprint(cli_params)
        return

    # TODO: everything
    return

upload.extended_info = {}


if __name__ == "__main__":
    print("artifactory webdav plugin tests")

