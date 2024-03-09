# configure_server

- Adds ssh keys
- Configures ssh forwarding for sudo
- Installs packages
    - git
    - gpg
    - mosh
    - tmux
    - vim
- Sets locale
- Sets timezone
- Runs ansible roles:
    - geerlingguy.security
    - ubuntu_disable_ads
    - fish_install
    - configure_dotfiles

## Status: Production

