# tests/roles/github_release_install is a symlink back to the role (the Ansible fixture test needs
# it, see ansible/tests/README.md). Without this pytest recurses through it and collects the same
# file over and over.
collect_ignore = ["roles"]
