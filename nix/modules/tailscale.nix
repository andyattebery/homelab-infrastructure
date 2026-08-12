# Capability: Tailscale with routing features on.
#
# Requires base.nix, which is where pkgs-unstable comes from -- base.nix sets
# _module.args.pkgs-unstable. mkHost always supplies base.nix, so this only bites if the
# module is reused outside that path.
{ pkgs, pkgs-unstable, ... }: {
  services.tailscale = {
    enable = true;
    useRoutingFeatures = "both";
    package = pkgs-unstable.tailscale;
  };

  # Disable UDP segmentation offload (tx-udp-segmentation) on physical NICs.
  # The Mellanox ConnectX-4 Lx (mlx5) on nas-host-01 mangles GSO-batched UDP
  # when offloading segmentation, corrupting forwarded WireGuard packets (Tailscale
  # exit node / subnet router) -> ~19% loss, throughput collapse to ~10 Mbps. TCP
  # TSO is unaffected, so only forwarded UDP suffers. Disabling the offload makes
  # the guest pre-segment in software (negligible CPU at these rates), which fixes
  # it. Applied to all forwarders because Proxmox HA can migrate these VMs onto the
  # affected host; harmless (and a fail-soft no-op) where the offload is fine/absent.
  #
  # Done as a oneshot, not a systemd .link: systemd.link has no UDPSegmentationOffload
  # option (only TCP/Generic), so it cannot target tx-udp-segmentation. The oneshot is
  # also naming-inert (a .link matching the NIC would take over NamePolicy).
  systemd.services.tailscale-disable-udp-gso = {
    description = "Disable tx-udp-segmentation (mlx5 corrupts forwarded WireGuard UDP)";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    path = [ pkgs.ethtool ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    # Physical NICs have a /sys/class/net/<if>/device symlink; lo, tun (tailscale0),
    # bridges and veth do not. Fail-soft where the feature is fixed/absent.
    script = ''
      for d in /sys/class/net/*; do
        if [ -e "$d/device" ]; then
          ethtool -K "$(basename "$d")" tx-udp-segmentation off || true
        fi
      done
    '';
  };
}
