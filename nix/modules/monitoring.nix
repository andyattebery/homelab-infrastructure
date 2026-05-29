{ ... }: {
  services.prometheus.exporters.node = {
    enable = true;
    enabledCollectors = [ "systemd" ];
    port = 9100;
  };
  networking.firewall.allowedTCPPorts = [ 9100 ];
}
