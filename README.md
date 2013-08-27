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


## Overview

As long as [RTFACT-4613: ](https://www.jfrog.com/jira/browse/RTFACT-4613) remains unresolved, 
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
configuration example can be found in the `indexing` directory.

You can use any host that has access to your Artifactory server for that, either via
a crontab entry, or by a job on a continuous integration server. 
The index hosts needs some configuration added too, 
for that simply call the script with the `setup` argument like this:

    sudo deb-index.sh setup http://repo.example.com/artifactory/

This installs the necessary tool packages, and adds a DAVFS mount to `/etc/fstab` and credentials to
`/etc/davfs2/secrets` (note that `vi` is called automatically to allow you to fill in the correct password 
for read-only access).

Next, describe your repositories in the `apt-ftparchive.conf` and `repo-«reponame».conf` configuration files;
see the provided examples and `man apt-ftparchive` for details.
These are always expected in the current directory, and temporary files are written
to subdirectories (`work` and `tmp`).

After finishing your configuration, you can create the Debian index files and upload them to Artifactory, by calling

    deb-index.sh refresh http://repo.example.com/artifactory/

in any normal user account (e.g. that of your continuous integration server, see the next section for a practical Jenkins example). 

Instead of passing the Artifactory URL on the comamnd line, you can set the `ARTIFACTORY_URL` environment variable.
Note that you also need to provide the Artifactory deployment credentials (of the form `user:pwd`) for
your new repository in either the `ARTIFACTORY_CREDENTIALS` environment variable, or the file `~/.artifactory.credentials`.
This account needs upload permissions to `debian-local`.


### Using Jenkins for Indexing

Using a Jenkins job is a nice environment for running your indexing task.
You can commit your repository configuration as described in the previous section to your local VCS,
let the Jenkins job check that out, and then run a *Shell Build Step* like follows:

    export ARTIFACTORY_URL=http://repo.example.com/artifactory/

    test -d artifactory-debian \
        && ( cd artifactory-debian && git pull ) \
        || git clone https://github.com/jhermann/artifactory-debian.git

    artifactory-debian/indexing/deb-index.sh refresh

The upload credentials are preferably injected into the job's environment using the `EnvInject` plugin,
so that they never appear in any console logs or other reports. 
For that, add the `ARTIFACTORY_CREDENTIALS` environment variable
to the "*Inject passwords to the build as environment variables*" setting of "*Build Environment*". 

Jenkins also allows you to trigger the index generation via a simple `curl` call or similar, using the Jenkins REST API.


## Installing Packages from Artifactory Repositories

The resulting repositories can be added to a machine like this:

    echo "deb http://repo.example.com/artifactory/debian-local noplat/" \
        >/etc/apt/sources.list.d/artifactory-noplat.list
    apt-get update

Then to give it a spin, try to list some packages only found in your new repository, using `apt-cache search`.
Or simply install a package via `apt-get`.


## Package Uploading

**NOT YET IMPLEMENTED**

`dput` conveniently provides a plugin directory for uploading methods, 
so we just use that to add Artifactory support.

The `http` plugin of `dput` could be used to PUT packages into Artifactory, 
but is thoroughly broken (at least the one I get on Ubuntu 12.04).
Besides that, it lacks some features I consider essential, so I decided to write a new plugin
specifically with Artifactory in mind. It tries to be compatible to the `http` plugin, 
and offers the following new features:

* `login` can take the form `account:password`, which avoids any password prompts (make sure you properly secure your `~/.dput.cf` in case you store passwords in it).
* `incoming` can be a full URL, and you can insert package metadata into the path, to support uploads into hierarchical repository structures (like `repo/package/version/package_version_arch.deb`).
* HTTPS support is provided by simply using a `https://…` URL.

For the variable replacements in `incoming`, the following keys are supported:

* `fqdn` — the value of the `fqdn` configuration option
* **TODO**

As already mentioned earlier, if you have the indexing job in Jenkins, 
you can trigger an index run via its REST API, 
and the `post_upload_command` configuration option comes into play here.

**TODO** Config example

Support for [dput-ng](http://people.debian.org/~paultag/dput-ng/) might be a good idea, when that one gets more traction
(didn't even know about it before I searched for existing `dput` plugins).

