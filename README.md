# Artifactory Debian Repository Support

`artifactory-debian` offers tools to use Artifactory as a Debian (APT) repository, 
and deploy DEB packages to it.

**Table of Contents**
- [Motivation](#motivation)
- [Repository Setup](#repository-setup)
	- [Artifactory Configuration](#artifactory-configuration)
	- [Indexing Host Configuration](#indexing-host-configuration)
- [Installing Packages from Artifactory Repositories](#installing-packages-from-artifactory-repositories)
- [Package Uploading](#package-uploading)


## Motivation

As long as [RTFACT-4613: ](https://www.jfrog.com/jira/browse/RTFACT-4613) remains unresolved, 
this is a way to manage your Debian packages with Artifactory here and now.

`deb-index.sh` is a little shell script that indexes a set of Debian repos located in Artifactory.

For package uploading, a `dput` plugin allows you to continue to use the standard Debian tool chain,
just with an additional `dput.cf` entry for your Artifactory installation.


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

**TODO** Insert sample screenshot of working repo.


### Indexing Host Configuration

For the Debian repositories to work together with `apt-get`, some index data needs
to be generated; this is what the script `deb-index.sh` does.
You can use any host that has access to your Artifactory server for that, either via
a crontab entry, or by a job on a continuous integration server. 
The index hosts needs some configuration added too, 
for that simply call the script with the `setup` argument like this:

    sudo deb-index.sh setup

This installs the necessary tool packages, and adds a DAVFS mount to `/etc/fstab` and credentials to
`/etc/davfs2/secrets` (note that `vi` is called automatically to allow you to fill in the correct password 
for read-only access).

Now you can create the Debian index files and upload them to Artifactory, by calling

    deb-index.sh refresh

in any normal user account (e.g. that of your continuous integration server). 
Note the you need to provide the Artifactory deployment credentials (of the form `user:pwd`) for
your new repository in either the `ARTIFACTORY_CREDENTIALS` environment variable, or the file `~/.artifactory.credentials`.
This account needs upload permissions to `debian-local`.

In Jenkins, this is best achieved using the `EnvInject` plugin, 
and adding the environment variable to the "*Inject passwords to the build as environment variables*" setting of "*Build Environment*". 
Jenkins also allows you to trigger the index generation via a simple `curl` call or similar, using the Jenkins REST API.


## Installing Packages from Artifactory Repositories

The resulting repositories can be added to a machine like this:

    echo "deb http://artifactory.example.com/artifactory/debian-local noplat/" \
        >/etc/apt/sources.list.d/artifactory-noplat.list
    apt-get update

Then to give it a spin, try to list some packages only found in your new repository, using `apt-cache search`.
Or simply install a package via `apt-get`.


## Package Uploading

**TODO** dput artifactory plugin

