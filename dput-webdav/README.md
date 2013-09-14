# ![Logo](https://raw.github.com/jhermann/artifactory-debian/master/doc/_static/artifactory-debian-logo.png) 'webdav' Upload Method for 'dput'

[dput-webdav](https://freecode.com/projects/dput-webdav) is a "dput" upload method plugin with extended WebDAV support.
It was written specifically with Artifactory and Bintray in mind.
It tries to be compatible with the "http" plugin, but offers additional features:
login credentials can include the password,
"incoming" can be a full URL (optionally containing dynamic package metadata, and supporting HTTPS),
and distributions can be mapped to repository names.

See [Package Uploading](https://github.com/jhermann/artifactory-debian/#package-uploading) for more.

