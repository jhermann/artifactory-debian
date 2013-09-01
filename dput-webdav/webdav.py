# -*- coding: utf-8 -*-
# pylint: disable=locally-disabled, star-args
""" WebDAV upload method for dput.

    Install to "/usr/share/dput/webdav.py".
"""
from __future__ import with_statement

import os
import sys
import cgi
import socket
import fnmatch
import getpass
import httplib
import urllib2
import urlparse
import unittest
from contextlib import closing

try:
    import dputhelper
except ImportError:
    sys.path.insert(0, "/usr/share/dput/helper")
    import dputhelper


# Block size for upload streaming
CHUNK_SIZE = 16 * 1024


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
        urllib2.HTTPPasswordMgr.__init__(self)
        self.login = login

    def find_user_password(self, realm, authuri):
        """Prompt for a password once and remember it, unless already provided in the configuration."""
        authuri = self.reduce_uri(authuri)[0]
        authinfo = urllib2.HTTPPasswordMgr.find_user_password(self, realm, authuri)

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
    config = dput.config # pylint: disable=no-member

    result = ""
    for section in config.sections():
        if (config.has_option(section, "fqdn")
                and config.get(section, "fqdn") == fqdn
                and config.has_option(section, section)):
            result = config.get(section, section)

    return result


def _distro2repo(distro, repo_mappings):
    """Map distribution names to repo names according to config settings."""
    # Parse the mapping config
    mappings = [(i.split('=', 1) if '=' in i else (i, i)) for i in repo_mappings.split()]

    # Try to find a match
    result = distro
    for pattern, target in mappings:
        if fnmatch.fnmatchcase(distro.lower(), pattern.lower()):
            result = target
            break

    trace("Mapped distro '%(distro)s' to '%(repo)s'", distro=distro, repo=result)
    return result


def _resolve_incoming(incoming, fqdn, changes='', cli_params=None, repo_mappings=""):
    """Resolve the given `incoming` value to a working URL."""
    # Build fully qualified URL
    scheme, netloc, path, params, query, anchor = urlparse.urlparse(incoming, scheme="http", allow_fragments=True)
    if scheme not in ("http", "https"):
        raise dputhelper.DputUploadFatalException("Unsupported URL scheme '%s'" % scheme)
    url = urlparse.urlunparse((scheme, netloc or fqdn, path.rstrip('/') + '/', params, query, None))

    # Parse anchor to parameters
    url_params = dict(cgi.parse_qsl(anchor or '', keep_blank_values=True))

    # Read changes from stream or file
    pkgdata = {}
    if changes:
        try:
            changes.read # pylint: disable=maybe-no-member
        except AttributeError:
            with closing(open(changes, "r")) as handle:
                changes = handle.read()
        else:
            changes = changes.read() # pylint: disable=maybe-no-member

        # TODO: pkgdata = ...

    # Interpolate `url`
    pkgdata.update(dict(
        fqdn=fqdn, repo=_distro2repo(pkgdata.get("distribution", "unknown"), repo_mappings),
    ))
    pkgdata.update(cli_params or {})
    try:
        url.format
    except AttributeError:
        url = url % pkgdata # Python 2.5
    else:
        url = url.format(**pkgdata) # Python 2.6+

    trace("Resolved incoming to `%(url)s' params=%(params)r", url=url, params=url_params)
    return url, url_params


def _dav_put(filepath, url, login, progress=None): # pylint: disable=too-many-locals
    """Upload `filepath` to given `url` (referring to a WebDAV collection)."""
    basename = os.path.basename(filepath)
    fileurl = urlparse.urljoin(url.rstrip('/') + '/', basename)

    sys.stdout.write("  Uploading %s: " % basename)
    sys.stdout.flush()
    size = os.path.getsize(filepath)

    with closing(open(filepath, 'r')) as handle:
        if progress:
            handle = dputhelper.FileWithProgress(handle, ptype=progress, progressf=sys.stdout, size=size)
        trace("HTTP PUT to URL: %s" % fileurl)
        scheme, netloc, path, params, query, _ = urlparse.urlparse(fileurl)

        try:
            # TODO: use "requests"?!
            conn = (httplib.HTTPSConnection if scheme == "https" else httplib.HTTPConnection)(netloc)
            try:
                conn.putrequest("PUT", urlparse.urlunparse((None, None, path, params, query, None)))#, skip_accept_encoding=True
                conn.putheader("User-Agent", "dput")
                conn.putheader("Authorization", 'Basic %s' % login.encode('base64').strip())
                conn.putheader("Connection", "close")
                conn.putheader("Content-Length", str(size))
                conn.endheaders()

                while True:
                    data = handle.read(CHUNK_SIZE)
                    if not data:
                        break
                    conn.send(data)

                resp = conn.getresponse()
                if 200 <= resp.status <= 299:
                    print " done."
                #elif res.status == 401 and not auth_headers:
                    #print "need authentication."
                    #auth_headers = AuthHandlerHackAround(url, res.msg, pwman).get_auth_headers()
                elif resp.status == 401:
                    print " unauthorized."
                    raise urllib2.URLError("Upload failed as unauthorized (%s),"
                        " maybe wrong username or password?" % resp.reason)
                else:
                    print " failed."
                    raise urllib2.URLError("Unexpected HTTP status %d %s" % (resp.status, resp.reason))

                resp.read() # eat response body
            finally:
                conn.close()
        except httplib.HTTPException, exc:
            raise urllib2.URLError(exc)


def upload(fqdn, login, incoming, files_to_upload, # pylint: disable=too-many-arguments, too-many-locals
        debug, dummy, progress=None):
    """Upload the files via WebDAV."""
    assert sys.version_info >= (2, 5), "Your snake is a rotting corpse"
    trace.debug = bool(debug)

    try:
        login = _resolve_credentials(login)

        # Try to get host argument from command line
        if upload.extended_info:
            host_config = dict(upload.extended_info["config"].items(upload.extended_info["host"]))
            host_argument = host_config.get(upload.extended_info["host"], "")
        else:
            host_config = {}
            host_argument = get_host_argument(fqdn)
        cli_params = dict(cgi.parse_qsl(host_argument, keep_blank_values=True))

        # Prepare for uploading
        incoming, repo_params = _resolve_incoming(incoming, fqdn, cli_params=cli_params,
            repo_mappings=host_config.get("repo_mappings", ""))
        repo_params.update(cli_params)
        mindepth = int(repo_params.get("mindepth", "0"), 10)
        overwrite = int(repo_params.get("overwrite", "0"), 10)
        # TODO: auth_handler = PromptingPasswordMgr(login)

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
        else:
            # TODO: Check if .changes file already exists
            #if not overwrite:
            # TODO: And also check for minmal path depth
            #if mindepth:

            # Upload the files in the given order
            for filepath in files_to_upload:
                _dav_put(filepath, incoming, login, progress)
    except (dputhelper.DputUploadFatalException, socket.error, urllib2.URLError, EnvironmentError), exc:
        print >> sys.stderr, "FATAL: %s" % exc
        sys.exit(1)

upload.extended_info = {}


#
# Unit Tests
#

class WebdavTest(unittest.TestCase): # pylint: disable=too-many-public-methods
    """Local unittests."""

    DISTRO2REPO_DATA = [
        ("unknown", "incoming"),
        ("foobar", "incoming"),
        ("unstable", "snapshots"),
        ("snapshots", "snapshots"),
        ("foo-experimental", "snapshots"),
        ("bar-experimental", "snapshots"),
    ]

    def test_distro2repo(self):
        """Test distribution mapping."""
        cfg = "snapshots unstable=snapshots *-experimental=snapshots *=incoming"

        for distro, repo in self.DISTRO2REPO_DATA:
            result = _distro2repo(distro, cfg)
            self.assertEquals(result, repo)

    def test_resolve_incoming(self):
        """Test URL resolving."""
        result, params = _resolve_incoming("incoming", "repo.example.com:80")
        self.assertEquals(result, "http://repo.example.com:80/incoming/")
        self.assertEquals(params, {})

        result, _ = _resolve_incoming("https:///incoming/", "repo.example.com:80")
        self.assertEquals(result, "https://repo.example.com:80/incoming/")

        result, _ = _resolve_incoming("//explicit/incoming/", "repo.example.com:80")
        self.assertEquals(result, "http://explicit/incoming/")

        result, _ = _resolve_incoming("//{fqdn}/incoming/", "repo.example.com:80")
        self.assertEquals(result, "http://repo.example.com:80/incoming/")

        _, params = _resolve_incoming("incoming#a=1&b=c", "")
        self.assertEquals(params, dict(a="1", b="c"))

        self.assertRaises(dputhelper.DputUploadFatalException, _resolve_incoming, "file:///incoming/", "")


if __name__ == "__main__":
    print("artifactory webdav plugin tests")
    unittest.main()

