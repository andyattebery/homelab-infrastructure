{
  domainName = "{{ op://Personal/Home Lab/domains/internal }}";
  subnetCidr = "{{ op://Personal/Home Lab/network/internal subnet cidr }}";
  dnsServerVip = "{{ op://Personal/Home Lab/dns/vip }}";
  acmeEmail = "{{ op://Personal/Certbot Email/notesPlain }}";

  network-03 = {
    adguardhomeUsername = "{{ op://Personal/adguardhome-03/username }}";
    adguardhomePasswordHash = "{{ op://Personal/adguardhome-03/config/hash }}";
  };
}
