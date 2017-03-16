# -*- coding: utf-8 -*-
# pylint: disable=locally-disabled, bad-continuation
""" WebDAV upload method for dput.

    Install to "/usr/share/dput/webdav.py".
"""
from __future__ import with_statement, print_function

import io
import re
import os
import sys
import cgi
import netrc
import socket
import fnmatch
import getpass
import hashlib
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
    sys.stdout.flush()
    sys.stderr.write("webdav: " + (msg % kwargs) + "\n")
    sys.stderr.flush()


def _resolve_credentials(fqdn, login):
    """Look up special forms of credential references."""
    result = login
    if "$" in result:
        result = os.path.expandvars(result)

    if result.startswith("netrc:"):
        result = result.split(':', 1)[1]
        if result:
            result = os.path.abspath(os.path.expanduser(result))
        accounts = netrc.netrc(result or None)
        account = accounts.authenticators(fqdn)
        if not account or not(account[0] or account[1]):
            raise dputhelper.DputUploadFatalException("Cannot find account for host %s in %s netrc file" % (
                fqdn, result or "default"))

        # account is (login, account, password)
        user, pwd = account[0] or account[1], account[2] or ""
        result = "%s:%s" % (user, pwd)
    else:
        if result.startswith("file:"):
            result = os.path.abspath(os.path.expanduser(result.split(':', 1)[1]))
            with closing(io.open(result, 'r', encoding='utf-8')) as handle:
                result = handle.read().strip()

        try:
            user, pwd = result.split(':', 1)
        except ValueError:
            user, pwd = result, ""

    trace("Resolved login credentials to %(user)s:%(pwd)s", user=user, pwd='*' * len(pwd))
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
    scheme, netloc, path, matrix_params, query, anchor = urlparse.urlparse(incoming, scheme="http", allow_fragments=True)
    if scheme not in ("http", "https"):
        raise dputhelper.DputUploadFatalException("Unsupported URL scheme '%s'" % scheme)
    url = urlparse.urlunparse((scheme, netloc or fqdn, path.rstrip('/') + '/', '', query, None))

    # Parse anchor to parameters
    url_params = dict(cgi.parse_qsl(anchor or '', keep_blank_values=True))

    # Read changes from stream or file
    pkgdata = {}
    if changes:
        try:
            changes + ""
        except TypeError:
            try:
                changes = changes.read() # pylint: disable=maybe-no-member
            except AttributeError:
                raise dputhelper.DputUploadFatalException(
                    "Expected a file-like object with a change record, but got %r" % changes)
        else:  # a string
            if '\n' not in changes:
                with closing(io.open(changes, 'r', encoding='utf-8')) as handle:
                    changes = handle.read()

        if changes.startswith("-----BEGIN PGP SIGNED MESSAGE-----"):
            # Let someone else check this, we don't care a bit; gimme the data already
            trace("Extracting package metadata from PGP signed message...")
            changes = changes.split("-----BEGIN PGP")[1].replace('\r', '').split('\n\n', 1)[1]

        pkgdata = dict([(key.lower().replace('-', '_'), val.strip())
            for key, val in rfc2822_parser.HeaderParser().parsestr(changes).items()
        ])
        if 'architecture' in pkgdata:
            # This is a bit hackish, but Artiactory wants it that way
            pkgdata['deb_architecture'] = ';deb.architecture='.join(pkgdata['architecture'].split())

    # Extend changes metadata
    pkgdata["loginuser"] = login.split(':')[0]
    if "version" in pkgdata:
        pkgdata["epoch"], pkgdata["upstream"] = '', re.split(r"[-~]", pkgdata["version"])[0]
        if ':' in pkgdata["upstream"]:
            pkgdata["epoch"], pkgdata["upstream"] = pkgdata["upstream"].split(':', 1)
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
            matrix_params = matrix_params % pkgdata
        else:
            url = url.format(**pkgdata) # Python 2.6+
            matrix_params = matrix_params.format(**pkgdata)
        matrix_params = matrix_params.replace(' ', '+')
    except KeyError, exc:
        raise dputhelper.DputUploadFatalException("Unknown key (%s) in incoming templates '%s'" % (exc, incoming))

    trace("Resolved incoming to `%(url)s' params=%(params)r", url=url, params=url_params)
    return url, matrix_params, url_params


def _url_connection(url, method, skip_host=False, skip_accept_encoding=False):
    """Create HTTP[S] connection for `url`."""
    scheme, netloc, path, params, query, _ = urlparse.urlparse(url)
    result = conn = (httplib.HTTPSConnection if scheme == "https" else httplib.HTTPConnection)(netloc)
    try:
        conn.debuglevel = int(trace.debug)
        conn.putrequest(method, urlparse.urlunparse((None, None, path, params, query, None)), skip_host, skip_accept_encoding)
        conn.putheader("User-Agent", "dput")
        conn.putheader("Connection", "close")
        conn = None  # return open connections as result
    finally:
        if conn:
            conn.close()  # close in case of errors

    return result


def _file_url(filepath, url):
    """Return URL for the given `filepath` in the DAV collection `url`."""
    basename = os.path.basename(filepath)
    return urlparse.urljoin(url.rstrip('/') + '/', basename)


def _dav_put(filepath, url, matrix_params, login, progress=None):
    """Upload `filepath` to given `url` (referring to a WebDAV collection)."""
    fileurl = _file_url(filepath, url)
    if matrix_params:
        fileurl += ';' + matrix_params
    sys.stdout.write("  Uploading %s: " % os.path.basename(filepath))
    sys.stdout.flush()
    size = os.path.getsize(filepath)

    hashes = dict([(x, getattr(hashlib, x)()) for x in ("md5", "sha1", "sha256")])
    with closing(io.open(filepath, 'rb')) as handle:
        while True:
            data = handle.read(CHUNK_SIZE)
            if not data:
                break
            for hashval in hashes.values():
                hashval.update(data)

    with closing(io.open(filepath, 'rb')) as handle:
        if progress:
            handle = dputhelper.FileWithProgress(handle, ptype=progress, progressf=sys.stdout, size=size)
        trace("HTTP PUT to URL: %s" % fileurl)

        try:
            conn = _url_connection(fileurl, "PUT")
            try:
                conn.putheader("Authorization", 'Basic %s' % login.encode('base64').replace('\n', '').strip())
                conn.putheader("Content-Length", str(size))
                for algo, hashval in hashes.items():
                    conn.putheader("X-Checksum-" + algo.capitalize(), hashval.hexdigest())
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
                    print(" done.")
                #elif res.status == 401 and not auth_headers:
                    #print "need authentication."
                    #auth_headers = AuthHandlerHackAround(url, res.msg, pwman).get_auth_headers()
                elif resp.status == 401:
                    print(" unauthorized.")
                    raise urllib2.URLError("Upload failed as unauthorized (%s),"
                        " maybe wrong username or password?" % resp.reason)
                else:
                    print(" failed.")
                    raise urllib2.URLError("Unexpected HTTP status %d %s" % (resp.status, resp.reason))

                resp.read() # eat response body
            finally:
                conn.close()
        except httplib.HTTPException, exc:
            raise urllib2.URLError(exc)


def _check_url(url, login, allowed, mindepth=0):
    """Check if HTTP GET `url` returns a status code in `allowed`."""
    if mindepth:
        scheme, netloc, path, params, query, fragment = urlparse.urlparse(url)
        path = '/'.join(path.split('/')[:mindepth+1]).rstrip('/') + '/'
        url = urlparse.urlunparse((scheme, netloc, path, params, query, fragment))

    trace("Checking URL '%(url)s'", url=url)
    try:
        # Could use a HTTPBasicAuthHandler here, but meh!
        # Should use 'requests', but dependency hell.
        request = urllib2.Request(url)
        request.add_header("Authorization", 'Basic %s' % login.encode('base64').replace('\n', '').strip())
        with closing(urllib2.urlopen(request)) as handle:
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


def _get_host_argument(fqdn):
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


def _get_config_data(fqdn):
    """Get configuration section for the chosen host, and CLI host parameters."""
    # Without the patch applied, fall back to ugly hacks
    if not upload.extended_info:
        try:
            caller = sys._getframe(2) # pylint: disable=protected-access
        except AttributeError:
            pass # somehow not CPython
        else:
            config = caller.f_globals.get("config")
            host = caller.f_locals.get("host")
            del caller
            if config and host:
                upload.extended_info = dict(config=config, host=host)

    if upload.extended_info:
        host_config = dict(upload.extended_info["config"].items(upload.extended_info["host"]))
        host_argument = host_config.get(upload.extended_info["host"], "")
    else:
        host_config = {}
        host_argument = _get_host_argument(fqdn)
        log("WARN: Extended host configuration not available!")

    # Parse "host:key=val;..." argument from command line into a dict
    cli_params = dict(cgi.parse_qsl(host_argument.replace(',', ';'), keep_blank_values=True))

    return host_config, cli_params


def upload(fqdn, login, incoming, files_to_upload, # pylint: disable=too-many-arguments
        debug, dummy, progress=None):
    """Upload the files via WebDAV."""
    assert sys.version_info >= (2, 5), "Your snake is a rotting corpse (Python 2.5+ required)"
    trace.debug = bool(debug)

    try:
        host_config, cli_params = _get_config_data(fqdn)
        login = _resolve_credentials(fqdn, login)

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
        incoming, matrix_params, repo_params = _resolve_incoming(fqdn, login, incoming, changes=changes_file,
            cli_params=cli_params, repo_mappings=host_config.get("repo_mappings", ""))
        log("INFO: Destination base URL is\n    %(url)s", url=urllib2.quote(incoming, safe=":/~;#"))
        repo_params.update(cli_params)
        mindepth = int(repo_params.get("mindepth", "0"), 10)
        overwrite = int(repo_params.get("overwrite", "0"), 10)
        # TODO: Add ability to enter missing password via terminal
        #   auth_handler = PromptingPasswordMgr(login)

        # Special handling for integration test code
        if "integration-test" in cli_params:
            import pprint
            print("upload arguments = ", end="")
            pprint.pprint(dict((k, v) for k, v in locals().iteritems() if k in (
                "fqdn", "login", "incoming", "files_to_upload", "debug", "dummy", "progress")))
            print("host config = ", end="")
            pprint.pprint(host_config)
            print("host arguments = ", end="")
            pprint.pprint(cli_params)
        else:
            # TODO: "bintray" REST API support
            #   POST /packages/:subject/:repo
            #   POST /packages/:subject/:repo/:package/versions

            # Check if .changes file already exists
            if not overwrite and changes_file:
                try:
                    _check_url(_file_url(changes_file, incoming), login, [404])
                except urllib2.HTTPError, exc:
                    raise dputhelper.DputUploadFatalException("Overwriting existing changes at '%s' not allowed: %s" % (
                        _file_url(changes_file, incoming), exc))

            # Check for existence of target path with minimal depth
            if mindepth:
                try:
                    _check_url(incoming, login, range(200, 300), mindepth=mindepth)
                except urllib2.HTTPError, exc:
                    raise dputhelper.DputUploadFatalException("Required repository path '%s' doesn't exist: %s" % (
                        exc.filename, exc))

            # Upload the files in the given order
            for filepath in files_to_upload:
                if "simulate" in cli_params:
                    log("WOULD upload '%(filename)s'", filename=os.path.basename(filepath))
                else:
                    _dav_put(filepath, incoming, matrix_params, login, progress)
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
        result, _, params = _resolve_incoming("repo.example.com:80", "", "incoming")
        self.assertEquals(result, "http://repo.example.com:80/incoming/")
        self.assertEquals(params, {})

        result, _, _ = _resolve_incoming("repo.example.com:80", "", "https:///incoming/")
        self.assertEquals(result, "https://repo.example.com:80/incoming/")

        result, _, _ = _resolve_incoming("repo.example.com:80", "", "//explicit/incoming/")
        self.assertEquals(result, "http://explicit/incoming/")

        result, _, _ = _resolve_incoming("repo.example.com:80", "", py25_format("//{fqdn}/incoming/"))
        self.assertEquals(result, "http://repo.example.com:80/incoming/")

        _, _, params = _resolve_incoming("", "", "incoming#a=1&b=c")
        self.assertEquals(params, dict(a="1", b="c"))

        result, _, _ = _resolve_incoming("repo.example.com:80", "johndoe", py25_format("incoming/{loginuser}"))
        self.assertEquals(result, "http://repo.example.com:80/incoming/johndoe/")

        # Version parsing
        for version in (('', '1.2.3'), ('1', '2.3.4')):
            changes = '\n'.join([
                "Source: dput-webdav-version-test",
                "Version: {0}{1}{2}".format(version[0], ':' if version[0] else '', version[1]),
                ''])
            result, _, _ = _resolve_incoming("repo.example.com:80", "",
                py25_format("v/{epoch}/{upstream}"), changes=changes)
            self.assertEquals(result, "http://repo.example.com:80/v/{0}/{1}/".format(*version))

        # Matrix parameters
        result, matrix_params, _ = _resolve_incoming("repo.example.com:80", "", "/a/b;foo=bar;bar=foo")
        self.assertEquals(result, "http://repo.example.com:80/a/b/")
        self.assertEquals(matrix_params, "foo=bar;bar=foo")

        # Unsupported URL scheme
        self.assertRaises(dputhelper.DputUploadFatalException, _resolve_incoming, "", "", "file:///incoming/")

        # Unknown key
        self.assertRaises(dputhelper.DputUploadFatalException, _resolve_incoming,
            "", "", py25_format("http://example.com/incoming/{not_defined_ever}/"))


if __name__ == "__main__":
    import mock

    print("artifactory webdav plugin tests")
    #trace.debug = True
    unittest.main()
