# ![Logo](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/artifactory-debian-logo.png) Debian Repositories in Artifactory

`artifactory-debian` offers tools to use [Artifactory](http://www.jfrog.com/) as a Debian (APT) repository,
and deploy DEB packages to it. Also see [the wiki](https://github.com/jhermann/artifactory-debian/wiki).

| **dput-webdav** | **Open HUB** |
|:-------------:|:-------------:|
| [![Travis Status](https://travis-ci.org/jhermann/artifactory-debian.png?branch=master)](https://travis-ci.org/jhermann/artifactory-debian)  [![Download](https://api.bintray.com/packages/jhermann/deb/dput-webdav/images/download.svg) ](https://bintray.com/jhermann/deb/dput-webdav/_latestVersion) | [![Ohloh stats](https://www.ohloh.net/p/artifactory-debian/widgets/project_thin_badge.gif)](https://www.ohloh.net/p/artifactory-debian) |

**Table of Contents**
- [Motivation and Overview](#motivation-and-overview)
- [Repository Setup](#repository-setup)
	- [Artifactory Configuration](#artifactory-configuration)
	- [Indexing Host Configuration](#indexing-host-configuration)
- [Installing Packages from Artifactory Repositories](#installing-packages-from-artifactory-repositories)
- [Package Uploading](#package-uploading)
	- ['webdav' Upload Method for 'dput'](#webdav-upload-method-for-dput)
	- [Installing the 'webdav' Plugin](#installing-the-webdav-plugin)
	- ['webdav' Plugin Configuration](#webdav-plugin-configuration)
	- [Uploading to Bintray](#uploading-to-bintray)
- [Acknowledgements](#acknowledgements)


## Motivation and Overview

Principles of *Continuous Delivery* mandate that you propagate a binary artifact,
once it's built, unchanged through the different quality gates and deployment stages of
your delivery pipeline. The need for keeping them in ideally a single place becomes obvious
pretty fast, together with similar build artifacts like Java JARs.

Artifactory is a repository server for binaries that can provide such a place, and offers the
additional advantage of attribute management on top of storing the contained files.
With that you can for example add cryptographic signatures of passed quality gates and the like,
when a candidate release progresses through the pipeline.

:mega: | Starting with version 3.3, Artifactory can handle Debian repositories natively (see [RTFACT-4613](https://www.jfrog.com/jira/browse/RTFACT-4613)). This project enabled you to manage your Debian packages within Artifactory before that, and still provides the `dput` plugin for easy uploading to a repository using the standard Debian tool chain.
----: | :----

The following diagram shows a typical setup and how the components interact.
When a package maintainer uploads to Artifactory using `dput`,
a `post_upload_command` remotely triggers a Jenkins job that pulls
the repository configuration (from a local SCM) and the indexing code (from GitHub).
That job then scans the available repositories using a read-only `davfs2` mount,
creates new index files, and finally uploads those back into Artifactory.
Users can then download the index files via `apt-get update` and install available packages as usual,
without realizing they're accessing an Artifactory server, except for the specific `apt` source definition syntax
(for details see [Installing Packages from Artifactory Repositories](#installing-packages-from-artifactory-repositories)).

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
    && ( cd artifactory-debian && git pull --ff-only ) \
    || git clone "https://github.com/jhermann/artifactory-debian.git"

artifactory-debian/indexing/deb-index.sh refresh
```

* Start the job via *Build Now*.
* Check in the Jenkins log and Artifactory web interface that the index files were generated and uploaded (cf. above screenshot).

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
[GitHub master build](https://huschteguzzel.de/hudson/job/dput-webdav/lastSuccessfulBuild/artifact/dput-webdav_1%7Emaster_all.deb)
and install it with either `dpkg -i` or directly from your browser, using the *Ubuntu Software Center* or a similar tool.

To install a **release version** via adding [Bintray](https://bintray.com/jhermann/deb/dput-webdav) as a package source, run these commands as `root`:

```sh
echo "deb http://dl.bintray.com/jhermann/deb /" \
    >/etc/apt/sources.list.d/bintray-jhermann.list
apt-get update
apt-get install -o "APT::Get::AllowUnauthenticated=yes" dput-webdav
```


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
# repo_mappings = unstable=snapshots *-experimental=snapshots *=incoming

# trigger Jenkins reindex job after successful upload
#post_upload_command = curl -k "<JENKINS_URL>/job/artifactory-debian-reindex/build?token=DOIT&cause=dput+upload"
```

* Call `⍽ echo -n "«username»:«password»" >~/.artifactory.credentials; chmod 600 ~/.artifactory.credentials` with your credentials filled in (put a space in front to exclude the command from shell history).

The above `~/.dput.cf` works with the indexing solution contained in this project.
If by now you use the *built-in* Debian repository type of Artifactory,
remove or comment the `post_upload_command` (it's not longer needed, indexing is automatic),
and change the `incoming` value as follows:

```ini
incoming = http://{fqdn}/artifactory/debian-local/pool/{source}/{upstream};deb.architecture={deb_architecture};deb.component=local;deb.distribution={repo}#mindepth=3&overwrite=0
```

Replace the `debian-local` path component if you named your repository differently.

To fully understand the `dput` WebDAV plugin configuration and be able to customize it,
read [WebDAV Plugin Configuration](https://github.com/jhermann/artifactory-debian/wiki/WebDAV-Plugin-Configuration).
Also refer to `man dput.cf` for the common configuration options shared by all upload methods.


### Uploading to Bintray

To use the `webdav` plugin for uploads to [Bintray](https://bintray.com/),
add this configuration to your workstation's user account:

* Extend your `~/.dput.cf` with this snippet:

```ini
[bintray]
method = webdav
fqdn = api.bintray.com
login = netrc:
incoming = https://{fqdn}/content/{loginuser}/deb/{source}/{upstream}/#mindepth=0&overwrite=1
allow_unsigned_uploads = 1
```

* Put your login name and API key into `~/.netrc` (and don't forget to `chmod 600` that file); the API key you'll find in [your profile](https://bintray.com/profile/edit) when you click on `API Key` in the sidebar menu:

```
machine api.bintray.com
    login YOURUSERNAME
    password 00...YOURAPIKEY...ff
```


As an example, the following is the log of the first release, where `dput-webdav` uploaded itself:

```sh
$ dput bintray dput-webdav*changes
Uploading to bintray (via webdav to api.bintray.com):
  Uploading dput-webdav_1.0.dsc:  done.
  Uploading dput-webdav_1.0.tar.gz: / done.
  Uploading dput-webdav_1.0_all.deb: / done.
  Uploading dput-webdav_1.0_amd64.changes: / done.
Successfully uploaded packages.
```


## Acknowledgements

Thanks to…
* the authors of `dput`, `apt-ftparchive`, `davfs2`, `curl`, and `bash`.
* [Inkscape](http://inkscape.org/) and [Shutter](https://en.wikipedia.org/wiki/Shutter_%28software%29) for eye candy.
* [DocToc](http://doctoc.herokuapp.com/) and Thorsten Lorenz for easy TOC maintenance.
* [1&1](https://github.com/1and1) for free ☕ ☕ ☕ and ⌛.
