# Artifactory Debian Repository Support

`artifactory-debian` offers tools to use [Artifactory](http://www.jfrog.com/) as a Debian (APT) repository, 
and deploy DEB packages to it.

**Table of Contents**
- [Overview](#overview)
- [Repository Setup](#repository-setup)
	- [Artifactory Configuration](#artifactory-configuration)
	- [Indexing Host Configuration](#indexing-host-configuration)
	- [Using Jenkins for Indexing](#using-jenkins-for-indexing)
- [Installing Packages from Artifactory Repositories](#installing-packages-from-artifactory-repositories)
- [Package Uploading](#package-uploading)
	- ['webdav' Upload Method for 'dput'](#webdav-upload-method-for-dput)
	- [Installing the 'webdav' Plugin](#installing-the-webdav-plugin)
	- [Basic 'webdav' Configuration](#basic-webdav-configuration)
	- [Extended 'webdav' Configuration](#extended-webdav-configuration)
- [Acknowledgements](#acknowledgements)


## Overview

As long as [RTFACT-4613](https://www.jfrog.com/jira/browse/RTFACT-4613) remains unresolved, 
this is a way to manage your Debian packages within Artifactory here and now.

`deb-index.sh` is a little shell script that indexes a set of Debian repos located in Artifactory.

For package uploading, a `dput` plugin allows you to continue to use the standard Debian tool chain,
just with an additional `dput.cf` section describing your Artifactory installation.


## Repository Setup

### Artifactory Configuration

To create your Debian repositories in Artifactory, start by adding a *Repository Layout* named
`debian-default` with this *Artifact Path Pattern*:

    [orgPath]/[module]/[baseRev]/[module]-[baseRev](-[patchLevel<[.~0-9a-zA-Z]+>])(_[archTag<\w+>]).[ext]

Set the *Folder/File Integration Revision RegExp* fields to `.*`.

Then create a new Artifactory repository named `debian-local` using the new layout.
Note that within that *Artifactory* repository, you can have several *Debian* repositories in form of subfolders.
Packages in those *Debian* repositories go into `pkgname/pkgversion` subfolders 
(cf. `[orgPath]/[module]/[baseRev]` in the layout's path pattern).

In the Artifactory web interface, the final result will look like this…

![Sample screenshot of a working repository](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/artifactory-repo-browser.png)


### Indexing Host Configuration

For the Debian repositories to work together with `apt-get`, some index data needs
to be generated; this is what the script `deb-index.sh` does. The script and a
configuration example can be found in the 
[indexing](https://github.com/jhermann/artifactory-debian/tree/master/indexing) directory.
The following diagram shows a typical setup and how the components interact.

![Configuration & Data Flow](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/data-flow.png)

You can use any host that has access to your Artifactory server for indexing, and 
run the index task via either a crontab entry, or as a job on a continuous integration server. 
The index host needs some software and configuration added, 
for that simply call the script with the `setup` argument like this:

```sh
sudo ./deb-index.sh setup "http://repo.example.com/artifactory/"
```

This installs the necessary tool packages, and adds a DAVFS mount to `/etc/fstab` and credentials to
`/etc/davfs2/secrets`. Your configured editor is called automatically to allow you 
to fill in the Artifactory credentials for read-only access.

Next, describe your repositories in the `apt-ftparchive.conf` and `repo-«reponame».conf` configuration files;
see the provided examples and `man apt-ftparchive` for details.
These are always expected in the current directory, and temporary files are written
to subdirectories (`work` and `tmp`).

After finishing your configuration, you can create the Debian index files and upload them to Artifactory, by calling

```sh
./deb-index.sh refresh "http://repo.example.com/artifactory/"
```

in any normal user account (e.g. that of your continuous integration server, see the next section for a practical Jenkins example). 

Instead of passing the Artifactory URL on the comamnd line, you can set the `ARTIFACTORY_URL` environment variable.
Note that you also need to provide the Artifactory deployment credentials (of the form `user:pwd`) for
your new repository in either the `ARTIFACTORY_CREDENTIALS` environment variable, or the file `~/.artifactory.credentials`.
This account needs upload permissions to `debian-local`.


### Using Jenkins for Indexing

Using a Jenkins job is a nice environment for running your indexing task.
You can commit your repository configuration as described in the previous section to your local VCS,
let the Jenkins job check that out, and then run a *Shell Build Step* like follows:

```sh
export ARTIFACTORY_URL="http://repo.example.com/artifactory/"

test -d artifactory-debian \
    && ( cd artifactory-debian && git pull ) \
    || git clone "https://github.com/jhermann/artifactory-debian.git"

artifactory-debian/indexing/deb-index.sh refresh
```

The upload credentials are preferably injected into the job's environment using the `EnvInject` plugin,
so that they never appear in any console logs or other reports. 
For that, add the `ARTIFACTORY_CREDENTIALS` environment variable
to the *Inject passwords to the build as environment variables* setting of *Build Environment*. 

Jenkins also allows you to trigger the index generation via a simple `curl` call or similar, using the Jenkins REST API.


## Installing Packages from Artifactory Repositories

The resulting repositories can be added to a machine like this:

```sh
echo "deb http://repo.example.com/artifactory/debian-local noplat/" \
    >/etc/apt/sources.list.d/artifactory-noplat.list
apt-get update
```

Then to give it a spin, try to list some packages only found in your new repository, using `apt-cache search`.
Or simply install a package via `apt-get`.


## Package Uploading
**Not yet FULLY implemented**

### 'webdav' Upload Method for 'dput'

`dput` conveniently provides a plugin directory for uploading methods, 
so we just use that to add Artifactory support.
The `http` plugin of `dput` could be used to PUT packages into Artifactory, 
but is thoroughly broken (at least the one I get on Ubuntu 12.04).

Besides that, it lacks some features I consider essential, so I decided to write a new `webdav` plugin
specifically with Artifactory in mind. It tries to be compatible to the `http` plugin, 
and offers the following new features:
* `login` credentials can include the password.
* `incoming` can be a full URL, also containing dynamic (package) metadata.
* HTTPS support is provided by simply using a `https://…` URL.
* Some extended features like mapping distributions to repository names.

Support for [dput-ng](http://people.debian.org/~paultag/dput-ng/) might be a good idea, when that one gets more traction
(didn't even know about it before I searched for existing `dput` plugins).


### Installing the 'webdav' Plugin

**Package Installation**

Download the latest 
[GitHub master build](http://huschteguzzel.de/hudson/job/dput-webdav/lastSuccessfulBuild/artifact/dput-dav_0%7Emaster_all.deb)
and install it with either `dpkg -i` or directly from your browser, using the *Ubuntu Software Center* or a similar tool.

**Manual Installation**

If for some reason you can't use a packaged installation,
copy the plugin from GitHub using this command:

```sh
sudo bash -c "umask 0133; curl -skS -o /usr/share/dput/webdav.py \
    https://raw.github.com/jhermann/artifactory-debian/master/dput-webdav/webdav.py"
```

**Other Installation Options**

For an in-depth discussion of options, see the 
[Detailed Install Instructions](https://github.com/jhermann/artifactory-debian/wiki/Detailed-Install-Instructions)
wiki page.


### Basic 'webdav' Configuration
Refer to `man dput.cf` for the common configuration options shared by all upload methods. 
Here, only noteworthy differences are mentioned.

* To avoid any password prompts, `login` can take the form `account:password` (make sure you properly secure your `~/.dput.cf` in case you store passwords in it).
* If `login` contains `${envvar}` references, they are expanded; if the value starts with `file:`, the credentials are loaded from the given path.
* `incoming` can be a full URL, and you can insert package metadata into the path, to support uploads into hierarchical repository structures (like `«repo»/«package»/«version»/«package»_«version»_«arch».deb`).

For the variable replacements in `incoming`, the following keys are supported:

* metadata from the `.changes` file, most notably `date`, `source`, `binary`, `architecture`, `version`, `distribution`, and `urgency`.
* `fqdn` — The value of the `fqdn` configuration option.
* `repo` — The same as `distribution`, unless mapped like described in the next section.
* `upstream` — The upstream `version` (everything before the first dash or tilde), or for native packages the same as `version`.

On modern systems with Python 2.6 or 2.7 installed, you can use the `{variable}` syntax for replacements;
otherwise you have to fall back on `%(variable)s` instead.

You can also set some repository parameters in the URL's anchor, formatted like a query string (`key=val&...`):

* `mindepth` — The number of path components that must already exist (default: 0). You can use this to prevent accidental creation of new repositories, or packages.
* `overwrite` — Allows you to disable the check for an already existing `.changes` file at the target URL (set to 0 or 1; default: 0).

As mentioned earlier, if you have the indexing job in Jenkins,
a successful upload can trigger an automatic index run via its REST API,
and the `post_upload_command` configuration option comes into play here.

Here's a sample Artifactory host section:

```ini
[artifactory-debian]
method = webdav
fqdn = repo.example.com:80
login = uploader:password
incoming = http://{fqdn}/artifactory/debian-local/{repo}/{source}/{upstream}/#mindepth=3&overwrite=0
allow_unsigned_uploads = 1
# post_upload_command = curl ... http://jenkins/...
```

### Extended 'webdav' Configuration

Some custom `webdav` options need the `dput` patch applied, 
refer to [Installing the 'webdav' Plugin](#installing-the-webdav-plugin) for that.

The extended options are these:

* `repo_mappings` — Maps distribution names to repository names, as a whitespace separated list of `distribution=repo` pairs; if no mapping is found, the name is used unchanged. Distribution names are matched ignoring case, and may be glob patterns (see the example below). Mapping rules are checked in the order they appear, and the first match is used.

Here's an extended configuration example:

```ini
[artifactory-debian]
method = webdav
…
repo_mappings = precise=1204_Precise unstable=snapshots *-experimental=snapshots *=incoming
```


## Acknowledgements

Thanks to…
* the authors of `dput`, `apt-ftparchive`, `davfs2`, `curl`, and `bash`.
* [Inkscape](http://inkscape.org/) and [Shutter](https://en.wikipedia.org/wiki/Shutter_%28software%29) for eye candy.
* [DocToc](http://doctoc.herokuapp.com/) and Thorsten Lorenz for easy TOC maintenance.
* [1&1](https://github.com/1and1) for free ☕ ☕ ☕ and ⌛.

