{ ... }: {
  services.prometheus.exporters.node = {
    enable = true;
    enabledCollectors = [ "systemd" "textfile" ];
    port = 9100;
    extraFlags = [ "--collector.textfile.directory=/var/lib/node_exporter" ];
  };
}
