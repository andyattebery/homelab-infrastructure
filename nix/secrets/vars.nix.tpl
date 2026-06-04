{
  domainName = "{{ op://Personal/Home Lab/domains/internal }}";
  subnetCidr = "{{ op://Personal/Home Lab/network/internal subnet cidr }}";
  dnsServerVip = "{{ op://Personal/Home Lab/dns/vip }}";
  acmeEmail = "{{ op://Personal/Certbot Email/notesPlain }}";

  network-01 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome/config/password bcrypt hash }}";
  };

  network-02 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome-02/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome-02/config/password bcrypt hash }}";
  };

  network-03 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome-03/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome-03/config/password bcrypt hash }}";
  };

  nut = {
    upsSnmpAddress = "{{ op://Home Lab/ups-rack/config/address }}";
    upsSnmpCommunity = "{{ op://Home Lab/ups-rack/snmp v1/read write community }}";
  };
}
