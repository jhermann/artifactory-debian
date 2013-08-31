# ![Logo](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/artifactory-debian-logo.png) Debian Repositories in Artifactory

`artifactory-debian` offers tools to use [Artifactory](http://www.jfrog.com/) as a Debian (APT) repository, 
and deploy DEB packages to it. Also see [the wiki](https://github.com/jhermann/artifactory-debian/wiki).

| **dput-webdav** |
|:-------------:|
| [![Jenkins Status](http://huschteguzzel.de/hudson/buildStatus/icon?job=dput-webdav)](http://huschteguzzel.de/hudson/view/jhermann/job/dput-webdav/) |

**Table of Contents**
- [Overview](#overview)
- [Repository Setup](#repository-setup)
	- [Artifactory Configuration](#artifactory-configuration)
	- [Indexing Host Configuration](#indexing-host-configuration)
- [Installing Packages from Artifactory Repositories](#installing-packages-from-artifactory-repositories)
- [Package Uploading](#package-uploading)
	- ['webdav' Upload Method for 'dput'](#webdav-upload-method-for-dput)
	- [Installing the 'webdav' Plugin](#installing-the-webdav-plugin)
	- ['webdav' Plugin Configuration](#webdav-plugin-configuration)
- [Acknowledgements](#acknowledgements)


## Overview

As long as [RTFACT-4613](https://www.jfrog.com/jira/browse/RTFACT-4613) remains unresolved, 
this is a way to manage your Debian packages within Artifactory here and now.
It offers a shell script that indexes a set of Debian repos located in Artifactory,
and a `dput` plugin that allows you to continue to use the standard Debian tool chain.

The following diagram shows a typical setup and how the components interact.

![Configuration & Data Flow](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/data-flow.png)

In the Artifactory web interface, the final result after following the setup instructions below will look like this…

![Sample screenshot of a working repository](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/artifactory-repo-browser.png)


## Repository Setup

Detailed information about the initial repository setup can be found at 
[Configuration of Artifactory and Repository Indexing](https://github.com/jhermann/artifactory-debian/wiki/Configuration-of-Artifactory-and-Repository-Indexing).
What follows is a shorter, no-nonsense version.


### Artifactory Configuration

To create your Debian repositories in Artifactory, follow these steps:

* Login with an administrator account.
* Add a *Repository Layout* named `debian-default` with this *Artifact Path Pattern*:

```sh
[orgPath]/[module]/[baseRev]/[module]-[baseRev](-[patchLevel<[.~0-9a-zA-Z]+>])(_[archTag<\w+>]).[ext]
```

* Set the layout's *Folder/File Integration Revision RegExp* fields to `.*`, and save it.
* Create a new Artifactory repository named `debian-local` using the new layout.

Now you can instantly start to upload packages into `debian-local`.


### Indexing Host Configuration

In order for `apt-get` to find packages, index data needs to be generated (what `apt-get update` downloads).
This is what the script `deb-index.sh` does; the script and a configuration example can be found in the 
[indexing](https://github.com/jhermann/artifactory-debian/tree/master/indexing) directory.

You can use any host that has network access to your Artifactory server for indexing, and 
run the index task via either a crontab entry, or as a job on a continuous integration server. 
This describes a Jenkins setup, for using `cron` just adapt the Jenkins configuration steps accordingly.

**On your workstation**

* Describe your repositories in the `apt-ftparchive.conf` and `repo-«reponame».conf` configuration files;
see the provided examples and `man apt-ftparchive` for details. Commit them to your local version control.


**On a Jenkins slave**

* Open a shell session on the indexing host, and copy or clone this git repository.
* Call the script with the `setup` argument like this:

```sh
sudo ./deb-index.sh setup "http://repo.example.com/artifactory/"
```

* When your configured editor pops up with `/etc/davfs2/secrets`, fill in Artifactory credentials for read-only access.


**In the Jenkins web interface**

* Install the `EnvInject` Jenkins plugin, if you don't already have it.
* Create a Jenkins job bound to the slave where you called `deb-index.sh setup`:
  * Set the workspace checkout location to the configuration files you just committed.
  * Add the `ARTIFACTORY_CREDENTIALS` environment variable with an account (`user:pwd`) having uploading permission, at the *Inject passwords to the build as environment variables* setting of *Build Environment*. 
  * Add a *Shell Build Step* like follows:

```sh
export ARTIFACTORY_URL="http://repo.example.com/artifactory/"

test -d artifactory-debian \
    && ( cd artifactory-debian && git pull ) \
    || git clone "https://github.com/jhermann/artifactory-debian.git"

artifactory-debian/indexing/deb-index.sh refresh
```

* Start the job via *Build Now*.
* Check in the Jenkins log and Artifactory web interface that the index files were generated and uploaded (cf. above schreenshot).

And you're now ready to use your shiny new toy…


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
or have a version of `dput` other than `0.9.6` installed,
copy the plugin from GitHub using this command:

```sh
sudo bash -c "umask 0133; curl -skS -o /usr/share/dput/webdav.py \
    https://raw.github.com/jhermann/artifactory-debian/master/dput-webdav/webdav.py"
```

**Other Installation Options**

For an in-depth discussion of options, see the 
[Detailed Install Instructions](https://github.com/jhermann/artifactory-debian/wiki/Detailed-Install-Instructions)
wiki page.


### 'webdav' Plugin Configuration

Your `~/.dput.cf` needs a section describing your Artifactory service,
and the upload credentials are placed in an extra file, for easier permission management.
So all you need is to create two files:

* Edit `~/.dput.cf` to include the following snippet (with the appropriate `fqdn`):

```ini
[DEFAULT]
default_host_main = artifactory-debian
progress_indicator = 2

[artifactory-debian]
method = webdav
fqdn = repo.example.com:80
login = file:~/.artifactory.credentials
incoming = http://{fqdn}/artifactory/debian-local/{repo}/{source}/{upstream}/#mindepth=3&overwrite=0
allow_unsigned_uploads = 1
#run_lintian = 1
#check_version = 1
# post_upload_command = curl ... http://jenkins/...
# repo_mappings = unstable=snapshots *-experimental=snapshots *=incoming
```

* Call `⍽ echo -n "«username»:«password»" >~/.artifactory.credentials; chmod 600 ~/.artifactory.credentials` with your credentials filled in (put a space in front to exclude the command from shell history).

To fully understand the `dput` WebDAV plugin configuration and be able to customize it,
read [WebDAV Plugin Configuration](https://github.com/jhermann/artifactory-debian/wiki/WebDAV-Plugin-Configuration).
Also refer to `man dput.cf` for the common configuration options shared by all upload methods.


## Acknowledgements

Thanks to…
* the authors of `dput`, `apt-ftparchive`, `davfs2`, `curl`, and `bash`.
* [Inkscape](http://inkscape.org/) and [Shutter](https://en.wikipedia.org/wiki/Shutter_%28software%29) for eye candy.
* [DocToc](http://doctoc.herokuapp.com/) and Thorsten Lorenz for easy TOC maintenance.
* [1&1](https://github.com/1and1) for free ☕ ☕ ☕ and ⌛.

