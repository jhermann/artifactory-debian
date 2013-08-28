# -*- coding: utf-8 -*-
""" WebDAV upload method for dput.

    Install to "/usr/share/dput/webdav.py".
"""
import os, sys, httplib, urllib2, urlparse, getpass, cgi

try:
    import dputhelper
except ImportError:
    sys.path.insert(0, "/usr/share/dput/helper")
    import dputhelper


class PromptingPasswordMgr(urllib2.HTTPPasswordMgr):
    """ Custom password manager that prompts for a password once, if none is available otherwise.
        
        Based on code in dput 0.9.6 (http method).
    """

    def __init__(self, username):
        super(PromptingPasswordMgr, self).__init__()
        self.username = username

    def find_user_password(self, realm, authuri):
        """Prompt for a password once and remember it, unless already provided in the configuration."""
        authuri = self.reduce_uri(authuri)[0]
        authinfo = super(PromptingPasswordMgr, self).find_user_password(realm, authuri)

        if authinfo == (None, None):
            if ':' in self.username:
                authinfo = self.username.split(':', 1)
            else:
                password = getpass.getpass("    Password for %s:" % realm)
                self.add_password(realm, authuri, self.username, password)
                authinfo = self.username, password

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

    # Try to get host argument from command line
    host_argument = get_host_argument(fqdn)
    cli_params = dict(cgi.parse_qsl(host_argument, keep_blank_values=True))

    # Special handling for integration test code
    if "integration-test" in cli_params:
        import pprint
        print "upload arguments = ",
        pprint.pprint(dict((k, v) for k, v in locals().iteritems() if k in (
            "fqdn", "login", "incoming", "files_to_upload", "debug", "dummy", "progress")))
        print "host arguments = ",
        pprint.pprint(cli_params)
        return

    # TODO: everything
    return


if __name__ == "__main__":
    print("artifactory webdav plugin tests")

