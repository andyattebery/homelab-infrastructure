{
  domainName = "{{ op://Home Lab/Home Lab/domains/internal }}";
  subnetCidr = "{{ op://Home Lab/Home Lab/network/internal subnet cidr }}";
  dnsServerVip = "{{ op://Home Lab/Home Lab/dns/vip }}";
  acmeEmail = "{{ op://Personal/Certbot Email/notesPlain }}";

  network-01 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome/config/password bcrypt hash }}";
  };

  network-02 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome-02/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome-02/config/password bcrypt hash }}";
    # pi-rack's on-board NIC, pinned by MAC in hosts/pi-rack. The same field NIM uses for
    # pi-rack's DHCP reservation, so a board swap updates both.
    nicMacAddress = "{{ op://Home Lab/pi-rack/hardware/mac address }}";
  };

  network-03 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome-03/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome-03/config/password bcrypt hash }}";
  };

  nim = {
    unifiUsername = "{{ op://Home Lab/UniFi/users/network-inventory-manager username }}";
  };

  nut = {
    upsSnmpAddress = "{{ op://Home Lab/ups-rack/config/address }}";
    upsSnmpCommunity = "{{ op://Home Lab/ups-rack/snmp v1/read write community }}";
  };

  # Referenced by ID, not name: the name form of these references contains the SSID.
  pi-turntable = {
    wifiSsid = "{{ op://Private/gwck4n2ntjc7bpw5whlsemqdxa/5E8E08B4D29E46F792206B1C83ACDE04/ssid }}";
    # Only for the first-boot image (hosts/pi-turntable/image-wifi.nix); deployed generations
    # read the password from secrets.yaml. An indented string, so a " or \ in it stays literal.
    wifiPsk = ''{{ op://Private/gwck4n2ntjc7bpw5whlsemqdxa/5E8E08B4D29E46F792206B1C83ACDE04/password }}'';
  };
}
