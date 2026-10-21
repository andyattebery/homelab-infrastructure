# Image only: flake.nix adds this to packages.aarch64-linux.pi-turntable-image. default.nix never
# imports it.
#
# On first boot the host has no sops age key yet, so the Wi-Fi password default.nix reads from
# sops cannot be decrypted, and Wi-Fi is this host's only network. This gives the image's own
# generation the password from vars.nix instead. The first deploy replaces that generation, and
# every deployed generation reads the password from sops.
#
# Not pre-seeding the age key into the image instead: every host key decrypts all of
# secrets.yaml, so that image would carry a fleet-wide key. This copy costs the Wi-Fi password in
# plaintext in the image file, in the builder's store, and in the Pi's store until the first
# generation is garbage-collected.
{ lib, pkgs, vars, ... }: {
  networking.wireless.secretsFile = lib.mkForce
    (pkgs.writeText "pi-turntable-wifi-bootstrap" "wifi_psk=${vars.pi-turntable.wifiPsk}\n");
}
