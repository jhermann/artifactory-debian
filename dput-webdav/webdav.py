# -*- coding: utf-8 -*-
# pylint: disable=locally-disabled, star-args
""" WebDAV upload method for dput.

    Install to "/usr/share/dput/webdav.py".
"""
from __future__ import with_statement

import re
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
from email import parser as rfc2822_parser

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


def log(msg, **kwargs):
    """Emit log message to stderr."""
    sys.stderr.write("webdav: " + (msg % kwargs) + "\n")
    sys.stderr.flush()


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


def _resolve_incoming(fqdn, login, incoming, changes=None, cli_params=None, repo_mappings=""):
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

        pkgdata = dict([(key.lower().replace('-', '_'), val.strip())
            for key, val in rfc2822_parser.HeaderParser().parsestr(changes).items()
        ])

    # Extend changes metadata
    pkgdata["loginuser"] = login.split(':')[0]
    if "version" in pkgdata:
        pkgdata["upstream"] = re.split(r"[-~]", pkgdata["version"])[0]
    pkgdata.update(dict(
        fqdn=fqdn, repo=_distro2repo(pkgdata.get("distribution", "unknown"), repo_mappings),
    ))
    pkgdata.update(cli_params or {}) # CLI options can overwrite anything
    trace("Collected metadata:\n    %(meta)s", meta="\n    ".join(["%s = %s" % (key, val)
        for key, val in sorted(pkgdata.items())
        if '\n' not in val # only print 'simple' values
    ]))

    # Interpolate `url`
    try:
        try:
            url.format
        except AttributeError:
            url = url % pkgdata # Python 2.5
        else:
            url = url.format(**pkgdata) # Python 2.6+
    except KeyError, exc:
        raise dputhelper.DputUploadFatalException("Unknown key (%s) in incoming templates '%s'" % (exc, incoming))

    trace("Resolved incoming to `%(url)s' params=%(params)r", url=url, params=url_params)
    return url, url_params


def _url_connection(url, method, skip_host=False, skip_accept_encoding=False):
    """Create HTTP[S] connection for `url`."""
    scheme, netloc, path, params, query, _ = urlparse.urlparse(url)
    result = conn = (httplib.HTTPSConnection if scheme == "https" else httplib.HTTPConnection)(netloc)
    conn.debuglevel = int(trace.debug)
    try:
        conn.putrequest(method, urlparse.urlunparse((None, None, path, params, query, None)), skip_host, skip_accept_encoding)
        conn.putheader("User-Agent", "dput")
        conn.putheader("Connection", "close")
        conn = None
    finally:
        if conn:
            conn.close() # close in case of errors

    return result


def _file_url(filepath, url):
    """Return URL for the given `filepath` in the DAV collection `url`."""
    basename = os.path.basename(filepath)
    return urlparse.urljoin(url.rstrip('/') + '/', basename)


def _dav_put(filepath, url, login, progress=None):
    """Upload `filepath` to given `url` (referring to a WebDAV collection)."""
    fileurl = _file_url(filepath, url)
    sys.stdout.write("  Uploading %s: " % os.path.basename(filepath))
    sys.stdout.flush()
    size = os.path.getsize(filepath)

    with closing(open(filepath, 'r')) as handle:
        if progress:
            handle = dputhelper.FileWithProgress(handle, ptype=progress, progressf=sys.stdout, size=size)
        trace("HTTP PUT to URL: %s" % fileurl)

        try:
            conn = _url_connection(fileurl, "PUT")
            try:
                conn.putheader("Authorization", 'Basic %s' % login.encode('base64').replace('\n', '').strip())
                conn.putheader("Content-Length", str(size))
                conn.endheaders()

                conn.debuglevel = 0
                while True:
                    data = handle.read(CHUNK_SIZE)
                    if not data:
                        break
                    conn.send(data)
                conn.debuglevel = int(trace.debug)

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


def _check_url(url, allowed, mindepth=0):
    """Check if HTTP GET `url` returns a status code in `allowed`."""
    if mindepth:
        scheme, netloc, path, params, query, fragment = urlparse.urlparse(url)
        path = '/'.join(path.split('/')[:mindepth+1]).rstrip('/') + '/'
        url = urlparse.urlunparse((scheme, netloc, path, params, query, fragment))

    trace("Checking URL '%(url)s'", url=url)
    try:
        # TODO: Check requests need to use login credentials
        with closing(urllib2.urlopen(url)) as handle:
            handle.read()
            code = handle.code
            if code not in allowed:
                raise urllib2.HTTPError(url, code,
                    "Unallowed HTTP status %d (%s)" % (code, handle.msg),
                    handle.headers, None)
    except urllib2.HTTPError, exc:
        code = exc.code
        if code not in allowed:
            raise

    trace("Code %(code)d OK for URL '%(url)s'", url=url, code=code)


def upload(fqdn, login, incoming, files_to_upload, # pylint: disable=too-many-arguments
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

        # Handle .changes file
        changes_file = [i for i in files_to_upload if i.endswith(".changes")]
        if not changes_file:
            log("WARN: No changes file found in %(n)d files to upload", n=len(files_to_upload))
            changes_file = None
        else:
            if len(changes_file) > 1:
                log("WARN: More than one changes file found in %(n)d files to upload,"
                    " taking the 1st:\n    %(changes)s",
                    n=len(files_to_upload), changes="\n    ".join(changes_file))
            changes_file = changes_file[0]

        # Prepare for uploading
        incoming, repo_params = _resolve_incoming(fqdn, login, incoming, changes=changes_file,
            cli_params=cli_params, repo_mappings=host_config.get("repo_mappings", ""))
        repo_params.update(cli_params)
        mindepth = int(repo_params.get("mindepth", "0"), 10)
        overwrite = int(repo_params.get("overwrite", "0"), 10)
        # TODO: Add ability to enter missing password via terminal
        #   auth_handler = PromptingPasswordMgr(login)

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
            # TODO: "bintray" REST API support
            #   POST /packages/:subject/:repo
            #   POST /packages/:subject/:repo/:package/versions

            # Check if .changes file already exists
            if not overwrite and changes_file:
                try:
                    _check_url(_file_url(changes_file, incoming), [404])
                except urllib2.HTTPError, exc:
                    raise dputhelper.DputUploadFatalException("Overwriting existing changes at '%s' not allowed: %s" % (
                        _file_url(changes_file, incoming), exc))

            # Check for existence of target path with minimal depth
            if mindepth:
                try:
                    _check_url(incoming, range(200, 300), mindepth=mindepth)
                except urllib2.HTTPError, exc:
                    raise dputhelper.DputUploadFatalException("Required repository path '%s' doesn't exist: %s" % (
                        exc.filename, exc))

            # Upload the files in the given order
            for filepath in files_to_upload:
                _dav_put(filepath, incoming, login, progress)
    except (dputhelper.DputUploadFatalException, socket.error, urllib2.URLError, EnvironmentError), exc:
        log("FATAL: %(exc)s", exc=exc)
        sys.exit(1)

upload.extended_info = {}


#
# Unit Tests
#

def py25_format(template):
    """Helper for testing under Python 2.5."""
    return template if sys.version_info >= (2, 6) else template.replace("{", "%(").replace("}", ")s")


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
        result, params = _resolve_incoming("repo.example.com:80", "", "incoming")
        self.assertEquals(result, "http://repo.example.com:80/incoming/")
        self.assertEquals(params, {})

        result, _ = _resolve_incoming("repo.example.com:80", "", "https:///incoming/")
        self.assertEquals(result, "https://repo.example.com:80/incoming/")

        result, _ = _resolve_incoming("repo.example.com:80", "", "//explicit/incoming/")
        self.assertEquals(result, "http://explicit/incoming/")

        result, _ = _resolve_incoming("repo.example.com:80", "", py25_format("//{fqdn}/incoming/"))
        self.assertEquals(result, "http://repo.example.com:80/incoming/")

        _, params = _resolve_incoming("", "", "incoming#a=1&b=c")
        self.assertEquals(params, dict(a="1", b="c"))

        result, _ = _resolve_incoming("repo.example.com:80", "johndoe", py25_format("incoming/{loginuser}"))
        self.assertEquals(result, "http://repo.example.com:80/incoming/johndoe/")

        # Unsupported URL scheme
        self.assertRaises(dputhelper.DputUploadFatalException, _resolve_incoming, "", "", "file:///incoming/")

        # Unknown key
        self.assertRaises(dputhelper.DputUploadFatalException, _resolve_incoming,
            "", "", py25_format("http://example.com/incoming/{not_defined_ever}/"))


if __name__ == "__main__":
    print("artifactory webdav plugin tests")
    unittest.main()

